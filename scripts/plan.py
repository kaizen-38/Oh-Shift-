#!/usr/bin/env python3
"""Oh Shift! planner: 4-week load radar, Future Pull, and a week plan with floors and buffer.

Standard library only. Cubbie gathers Canvas, calendar and profile data and passes it in;
this script never reaches the network.

Commands (run from the Skill folder):
  plan.py profile --file profile.json | --show
  plan.py plan --input week.json [--minimum]
  plan.py replan --now <ISO time> [--minimum]
  plan.py add --file item.json
  plan.py log --block <id> | --task <id>  --status done|skipped [--actual-hours H]
  plan.py show
  plan.py radar [--now <ISO time>]
  plan.py stats
Add --sample to any command to use assets/sample_*.json in a throwaway folder.

Exit codes: 0 ok, 2 invalid input, 3 no profile saved, 4 unknown block or task, 5 no saved week.
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

SKILL_DIR = Path(__file__).resolve().parent.parent
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRIORITY = {"high": 3, "normal": 2, "low": 1}
STORM, BUSY, OK = 0.85, 0.70, 0.50
MIN_CHUNK, MAX_CHUNK, MAX_TASK_PER_DAY = 30, 120, 180
FRAGILE_MIN = 45
PEAKS = {"morning": (8 * 60, 12 * 60), "afternoon": (12 * 60, 17 * 60), "night": (19 * 60, 23 * 60),
         "evening": (17 * 60, 22 * 60)}


class Fail(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- storage

def state_dir(sample):
    if sample:
        return Path(tempfile.mkdtemp(prefix="oh-shift-sample-"))
    base = os.environ.get("SKILL_DATA_DIR")
    d = Path(base) if base else Path.home() / ".config" / "oh-shift"
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path, code=2, what=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise Fail(code, f"{what or path} not found")
    except json.JSONDecodeError as e:
        raise Fail(2, f"{what or path} is not valid JSON: {e.msg} at line {e.lineno}")


def write_json(path, data):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    tmp.replace(path)


def load_history(sd):
    p = sd / "history.json"
    if p.exists():
        return read_json(p)
    return {"log": [], "multipliers": {}, "task_done_hours": {}, "task_complete": [], "goal_done": {}}


# ---------------------------------------------------------------- time helpers

def parse_time(value, field):
    if not isinstance(value, str):
        raise Fail(2, f"{field} must be an ISO time like 2026-10-26T14:00:00-07:00")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Fail(2, f"{field} is not an ISO time: {value}")
    if dt.tzinfo is None:
        raise Fail(2, f"{field} needs a UTC offset, like -07:00: {value}")
    return dt


def parse_hhmm(value, field):
    try:
        h, m = value.split(":")
        h, m = int(h), int(m)
        assert 0 <= h <= 24 and 0 <= m < 60
        return h * 60 + m
    except Exception:
        raise Fail(2, f"{field} must be HH:MM, got {value!r}")


def get_tz(profile, now):
    name = profile.get("timezone")
    if name and ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return now.tzinfo or timezone.utc


def to_min(dt):
    return int(dt.timestamp() // 60)


def from_min(m, tz):
    return datetime.fromtimestamp(m * 60, tz)


def local_at(d, minutes, tz):
    """Absolute minute for local date d plus `minutes` after its midnight (may exceed 24h)."""
    base = datetime.combine(d, time(0), tzinfo=tz)
    return to_min(base) + minutes


def fmt(m, tz):
    return from_min(m, tz).strftime("%Y-%m-%d %H:%M")


def short_time(m, tz):
    dt = from_min(m, tz)
    s = dt.strftime("%I:%M%p").lstrip("0").lower().replace(":00", "")
    return s.replace("am", "a").replace("pm", "p")


def subtract(intervals, cut):
    cs, ce = cut
    out = []
    for s, e in intervals:
        if ce <= s or cs >= e:
            out.append((s, e))
            continue
        if s < cs:
            out.append((s, cs))
        if ce < e:
            out.append((ce, e))
    return out


def length(intervals):
    return sum(e - s for s, e in intervals)


def slug(s):
    return "".join(c if c.isalnum() else "-" for c in str(s).lower()).strip("-")


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


# ---------------------------------------------------------------- validation

def validate_profile(p):
    if not isinstance(p, dict):
        raise Fail(2, "profile must be a JSON object")
    for key in ("wake", "sleep"):
        parse_hhmm(p.get(key, "08:00" if key == "wake" else "00:00"), key)
    for i, c in enumerate(p.get("classes", [])):
        for k in ("title", "days", "start", "end"):
            if k not in c:
                raise Fail(2, f"classes[{i}].{k} is missing")
        for d in c["days"]:
            if d not in DAY_NAMES:
                raise Fail(2, f"classes[{i}].days has {d!r}; use Mon..Sun")
    ids = set()
    for i, g in enumerate(p.get("goals", [])):
        if "id" not in g or "name" not in g:
            raise Fail(2, f"goals[{i}] needs id and name")
        ids.add(g["id"])
        if g.get("type", "flexible") == "fixed":
            if not g.get("sessions"):
                raise Fail(2, f"goals[{i}] is fixed but has no sessions")
        elif not g.get("per_week") or not g.get("minutes"):
            raise Fail(2, f"goals[{i}] is flexible and needs per_week and minutes")
    for gid in p.get("floors", {}).get("goals", {}):
        if gid not in ids:
            raise Fail(2, f"floors.goals.{gid} does not match any goal id")
    for i, m in enumerate(p.get("floors", {}).get("meals", [])):
        for k in ("name", "earliest", "latest", "minutes"):
            if k not in m:
                raise Fail(2, f"floors.meals[{i}].{k} is missing")


def validate_week(w):
    if not isinstance(w, dict):
        raise Fail(2, "week must be a JSON object")
    parse_time(w.get("now"), "now")
    for i, t in enumerate(w.get("tasks", [])):
        validate_task(t, f"tasks[{i}]")
    for i, b in enumerate(w.get("busy", [])):
        validate_busy(b, f"busy[{i}]")


def validate_task(t, where):
    for k in ("id", "title", "due"):
        if k not in t:
            raise Fail(2, f"{where}.{k} is missing")
    parse_time(t["due"], f"{where}.due")
    if "unlock" in t and t["unlock"]:
        parse_time(t["unlock"], f"{where}.unlock")
    if not isinstance(t.get("estimate_hours", 2), (int, float)):
        raise Fail(2, f"{where}.estimate_hours must be a number")


def validate_busy(b, where):
    for k in ("title", "start", "end"):
        if k not in b:
            raise Fail(2, f"{where}.{k} is missing")
    if parse_time(b["end"], f"{where}.end") <= parse_time(b["start"], f"{where}.start"):
        raise Fail(2, f"{where} ends before it starts")


# ---------------------------------------------------------------- the model

class Planner:
    def __init__(self, profile, week, history, now, minimum=False, keep=None, implicit=None):
        self.p, self.w, self.h = profile, week, history
        self.keep = keep or []
        self.implicit = implicit or {"goals": {}, "task_hours": {}}
        self.now = now
        self.tz = get_tz(profile, now)
        self.now_m = to_min(now)
        self.minimum_forced = minimum
        local_now = now.astimezone(self.tz)
        today = local_now.date()
        # Sunday plans the coming Mon-Sun; any other day plans the rest of this week.
        self.anchor = today + timedelta(days=1) if today.weekday() == 6 else today - timedelta(days=today.weekday())
        self.today = today
        self.weeks = [self.anchor + timedelta(days=7 * k) for k in range(4)]
        self.horizon_days = [today + timedelta(days=i) for i in range((self.weeks[3] + timedelta(days=7) - today).days)]
        self.wake = parse_hhmm(profile.get("wake", "08:00"), "wake")
        sleep = parse_hhmm(profile.get("sleep", "00:00"), "sleep")
        self.sleep = sleep if sleep > self.wake else sleep + 24 * 60
        nwa = parse_hhmm(profile.get("no_work_after", "23:00"), "no_work_after")
        self.work_end = min(nwa if nwa > self.wake else nwa + 24 * 60, self.sleep)
        self.buffer_pct = max(0, min(40, profile.get("buffer_pct", 15))) / 100
        self.peak = PEAKS.get(profile.get("peak", "morning"), PEAKS["morning"])
        self.focus = int(float(profile.get("max_focus_hours", 5)) * 60)
        self.notes, self.warnings = [], []
        self.stars = {}
        for s in profile.get("north_stars", []):
            if s.get("course"):
                self.stars[s["course"].lower()] = s
        self._build_occupied()

    # --- fixed time

    def _build_occupied(self):
        tz = self.tz
        occ = []  # (start, end, title, kind)
        for c in self.p.get("classes", []):
            start, end = parse_hhmm(c["start"], "class start"), parse_hhmm(c["end"], "class end")
            frm = date.fromisoformat(c["from"]) if c.get("from") else None
            until = date.fromisoformat(c["until"]) if c.get("until") else None
            for d in self.horizon_days:
                if DAY_NAMES[d.weekday()] in c["days"] and (not frm or d >= frm) and (not until or d <= until):
                    occ.append((local_at(d, start, tz), local_at(d, end, tz), c["title"], "class"))
        for g in self.p.get("goals", []):
            if g.get("type") == "fixed":
                for s in g["sessions"]:
                    st, en = parse_hhmm(s["start"], "session start"), parse_hhmm(s["end"], "session end")
                    for d in self.horizon_days:
                        if DAY_NAMES[d.weekday()] == s["day"]:
                            occ.append((local_at(d, st, tz), local_at(d, en, tz), g["name"], "fixed"))
        for i, b in enumerate(self.w.get("busy", [])):
            s, e = to_min(parse_time(b["start"], "busy")), to_min(parse_time(b["end"], "busy"))
            occ.append((s, e, b["title"], "away" if b.get("away") else "busy"))
        self.occupied = occ

    def day_bounds(self, d):
        return local_at(d, self.wake, self.tz), local_at(d, self.sleep, self.tz), local_at(d, self.work_end, self.tz)

    def day_free(self, d):
        """Free intervals for work on day d (after now, before no-work-after), and the day's buffer minutes."""
        wake, sleep, work_end = self.day_bounds(d)
        free = [(max(wake, self.now_m), work_end)] if work_end > max(wake, self.now_m) else []
        for s, e, _, _ in self.occupied:
            free = subtract(free, (s, e))
        waking = max(0, sleep - max(wake, self.now_m))
        return free, int(waking * self.buffer_pct)

    def week_of(self, m):
        d = from_min(m, self.tz).date()
        for k in range(4):
            if self.weeks[k] <= d < self.weeks[k] + timedelta(days=7):
                return k
        return None if d >= self.weeks[0] else 0

    # --- tasks

    def tasks(self):
        out = []
        done = self.h.get("task_done_hours", {})
        complete = set(self.h.get("task_complete", []))
        mult = self.h.get("multipliers", {})
        for t in self.w.get("tasks", []):
            if t.get("submitted") or t["id"] in complete:
                continue
            due = to_min(parse_time(t["due"], "due"))
            if due <= self.now_m:
                continue
            course = t.get("course", "")
            m = mult.get(course, 1.0)
            est = float(t.get("estimate_hours", 2))
            need = round(est * m * 2) / 2
            remaining = max(0.0, need - float(done.get(t["id"], 0)) - self.implicit["task_hours"].get(t["id"], 0))
            if remaining <= 0:
                continue
            unlock = to_min(parse_time(t["unlock"], "unlock")) if t.get("unlock") else None
            star = self.stars.get(course.lower(), {})
            prio = PRIORITY.get(star.get("priority", "normal"), 2)
            weight = float(t.get("weight_pct") or 0)
            urgent = 10 if due - self.now_m < 48 * 60 else 0
            out.append({
                "id": t["id"], "title": t["title"], "course": course, "due": due, "unlock": unlock,
                "kind": t.get("kind", "task"), "hours": remaining, "est": est, "mult": m,
                "weight": weight, "prio": prio, "star": star.get("target"),
                "score": prio * 10 + min(weight, 40) + urgent, "url": t.get("url"),
            })
        out.sort(key=lambda x: (x["due"], -x["score"]))
        return out

    def lead_days(self, t):
        if t["kind"] == "exam":
            return 7
        return int(min(7, max(2, math.ceil(t["hours"] / 2))))

    def allocate(self, t):
        """Default just-in-time spread of a task's hours over the days before its due date -> {week: hours}."""
        due_day = from_min(t["due"] - 1, self.tz).date()
        start = max(self.today, due_day - timedelta(days=self.lead_days(t) - 1))
        if t["unlock"]:
            start = max(start, from_min(t["unlock"], self.tz).date())
        days = [start + timedelta(days=i) for i in range((due_day - start).days + 1)] or [due_day]
        per = t["hours"] / len(days)
        alloc = {}
        for d in days:
            k = self.week_of(local_at(d, 12 * 60, self.tz))
            if k is None:
                k = 0
            alloc[k] = alloc.get(k, 0) + per
        return alloc

    # --- goals and floors

    def goal_minutes(self, minimum, week_fraction=1.0):
        total = 0
        for g in self.goal_sessions(minimum, week_fraction):
            total += g["minutes"] * g["count"]
        return total

    def goal_sessions(self, minimum, week_fraction=1.0, done=None):
        floors = self.p.get("floors", {})
        out = []
        for g in self.p.get("goals", []):
            if g.get("type") == "fixed":
                continue
            per, mins = g["per_week"], g["minutes"]
            if minimum:
                f = floors.get("goals", {}).get(g["id"])
                if f:
                    per, mins = f.get("per_week", per), f.get("minutes", mins)
                else:
                    per = 0
            per = per - (done or {}).get(g["id"], 0)
            count = max(0, math.ceil(per * week_fraction - 1e-9))
            if count:
                out.append({"id": g["id"], "name": g["name"], "minutes": mins, "count": count,
                            "preferred": g.get("preferred"), "kind": "goal"})
        for c in floors.get("custom", []):
            per = c.get("per_week", 1) - (done or {}).get(c["name"], 0)
            count = max(0, math.ceil(per * week_fraction - 1e-9))
            if count:
                out.append({"id": c["name"], "name": c["name"], "minutes": c.get("minutes", 30), "count": count,
                            "preferred": c.get("preferred"), "kind": "floor"})
        return out

    def meal_minutes_per_day(self):
        return sum(m["minutes"] for m in self.p.get("floors", {}).get("meals", []))

    # --- radar

    def radar(self, tasks):
        demand = [0.0] * 4
        items = [[] for _ in range(4)]
        alloc = {}
        for t in tasks:
            a = self.allocate(t)
            alloc[t["id"]] = a
            for k, hrs in a.items():
                if k < 4:
                    demand[k] += hrs
            k_due = self.week_of(t["due"] - 1)
            if k_due is not None and k_due < 4:
                items[k_due].append(t)
        cap, goals, fixed_load = [], [], []
        for k in range(4):
            days = [self.weeks[k] + timedelta(days=i) for i in range(7)]
            usable, focus, frac_days = 0, 0, 0
            for d in days:
                if d < self.today:
                    continue
                free, buf = self.day_free(d)
                room = max(0, length(free) - buf - self.meal_minutes_per_day())
                if room > 0:
                    frac_days += 1
                usable += room
                focus += min(room, self.focus)
            frac = frac_days / 7 if k == 0 else 1.0
            g = self.goal_minutes(False, frac)
            cap.append(max(0, min(focus, usable - g)) / 60)
            goals.append(g / 60)
        busy_drivers = [[] for _ in range(4)]
        for s, e, title, kind in self.occupied:
            if kind in ("busy", "away") and e - s >= 60 and e > self.now_m:
                k = self.week_of(s)
                if k is not None and k < 4:
                    busy_drivers[k].append(title)
        return demand, cap, goals, items, alloc, busy_drivers

    def status_for(self, load, cap):
        ratio = load / cap if cap > 0 else (9 if load > 0 else 0)
        if ratio > STORM:
            return "storm", ratio
        if ratio > BUSY:
            return "busy", ratio
        if ratio > OK:
            return "ok", ratio
        return "light", ratio

    def future_pull(self, tasks, demand, cap, goals, alloc):
        pulls = []
        by_id = {t["id"]: t for t in tasks}
        for k in range(3, 0, -1):
            load = demand[k]
            if cap[k] <= 0 or load / cap[k] <= STORM:
                continue
            excess = load - 0.75 * cap[k]
            cands = [by_id[i] for i, a in alloc.items() if a.get(k, 0) > 0.01]
            cands.sort(key=lambda t: (-t["prio"], -t["hours"], t["due"]))
            for t in cands:
                if excess <= 0.25:
                    break
                movable = alloc[t["id"]][k]
                if t["kind"] != "exam" and t["hours"] >= 5:
                    movable = min(movable, t["hours"] * 0.5)
                for j in sorted(range(k), key=lambda j: (demand[j] / cap[j] if cap[j] else 9, -j)):
                    if excess <= 0.25 or movable <= 0.25:
                        break
                    week_end = local_at(self.weeks[j] + timedelta(days=7), 0, self.tz)
                    if t["unlock"] and t["unlock"] > week_end - 24 * 60:
                        continue
                    room = BUSY * cap[j] - demand[j]
                    if room < 1:
                        continue
                    hrs = math.floor(min(room, movable, excess) * 2) / 2
                    if hrs < 1:
                        continue
                    alloc[t["id"]][k] -= hrs
                    alloc[t["id"]][j] = alloc[t["id"]].get(j, 0) + hrs
                    demand[k] -= hrs
                    demand[j] += hrs
                    excess -= hrs
                    movable -= hrs
                    what = "review" if t["kind"] == "exam" else ("a first part" if t["hours"] >= 5 else "all of it")
                    pulls.append({"task": t["title"], "task_id": t["id"], "course": t["course"], "hours": hrs,
                                  "what": what, "from_week": self.weeks[k].strftime("%b %-d"),
                                  "to_week": self.weeks[j].strftime("%b %-d"),
                                  "why": f"{self.weeks[k].strftime('%b %-d')} week is overloaded"})
        return pulls

    # --- packing this week

    def pack(self, tasks, alloc, minimum, done_goals):
        tz = self.tz
        days = [d for d in self.horizon_days if max(self.today, self.weeks[0]) <= d < self.weeks[0] + timedelta(days=7)]
        free, cap = {}, {}
        for d in days:
            f, buf = self.day_free(d)
            free[d], cap[d] = f, max(0, length(f) - buf)
        used = {d: 0 for d in days}
        focus_used = {d: 0 for d in days}
        blocks = []

        def take(d, s, e):
            free[d] = subtract(free[d], (s, e))
            used[d] += e - s

        def find(d, want, lo, hi, minimum_len=None, respect_cap=True):
            room = cap[d] - used[d] if respect_cap else want
            want = min(want, room)
            need = minimum_len or want
            if want < need or need <= 0:
                return None
            for s, e in free[d]:
                s2, e2 = max(s, lo), min(e, hi)
                if e2 - s2 >= need:
                    return s2, s2 + min(want, e2 - s2)
            return None

        week_end = local_at(self.weeks[0] + timedelta(days=7), 0, tz)

        def task_minutes(t):
            hrs = t["hours"] if t["due"] <= week_end else alloc.get(t["id"], {}).get(0, 0)
            return int(math.ceil(hrs * 2 - 1e-9)) * 30

        task_want = {t["id"]: task_minutes(t) for t in tasks}
        sessions = self.goal_sessions(minimum, 1.0, done_goals)
        goal_need = {g["id"]: g["count"] for g in sessions}

        # keep pass (replans): leave unaffected future blocks exactly where they were
        kept_ids, kept_goal, kept_task, kept_days = set(), {}, {}, {}
        for b in sorted(self.keep, key=lambda x: x["s"]):
            d = from_min(b["s"], tz).date()
            if d not in free or b["s"] < self.now_m or not any(fs <= b["s"] and b["e"] <= fe for fs, fe in free[d]):
                continue
            n = b["e"] - b["s"]
            if b["kind"] == "task":
                tid = b.get("task_id")
                if tid not in task_want or kept_task.get(tid, 0) + n > task_want[tid]:
                    continue
                kept_task[tid] = kept_task.get(tid, 0) + n
                focus_used[d] += n
            elif b["kind"] in ("goal", "floor") and b.get("goal_id"):
                gid = b["goal_id"]
                if kept_goal.get(gid, 0) >= goal_need.get(gid, 0):
                    continue
                kept_goal[gid] = kept_goal.get(gid, 0) + 1
                kept_days.setdefault(gid, set()).add(d)
            elif b["kind"] not in ("meal", "floor"):
                continue
            if b["title"] == "Free evening":
                free[d] = subtract(free[d], (b["s"], b["e"]))
            else:
                take(d, b["s"], b["e"])
            kept_ids.add(b["id"])
            nb = {k: v for k, v in b.items() if k not in ("lock_in", "call")}
            if nb["kind"] == "task":
                tt = next(x for x in tasks if x["id"] == nb["task_id"])
                nb.update({"score": tt["score"], "due": tt["due"], "url": tt.get("url")})
            blocks.append(nb)

        # meals: never both removed on one day; shorten before removing
        for d in days:
            placed = 0
            meals = self.p.get("floors", {}).get("meals", [])
            for meal in meals:
                if f"{slug(meal['name'])}-{d.isoformat()}" in kept_ids:
                    placed += 1
                    continue
                lo = local_at(d, parse_hhmm(meal["earliest"], "meal"), tz)
                hi = local_at(d, parse_hhmm(meal["latest"], "meal"), tz)
                if hi <= self.now_m or any(k == "away" and overlap((s, e), (lo, hi)) for s, e, _, k in self.occupied):
                    placed += 1  # past, or the student is away: not this plan's job
                    continue
                got = None
                for mins in (meal["minutes"], 20, 15):
                    got = find(d, mins, lo, hi, mins, respect_cap=False)
                    if got:
                        break
                if got:
                    take(d, *got)
                    placed += 1
                    blocks.append({"id": f"{slug(meal['name'])}-{d.isoformat()}", "kind": "meal",
                                   "title": meal["name"], "s": got[0], "e": got[1]})
                else:
                    why = next((title for s, e, title, _ in self.occupied if overlap((s, e), (lo, hi))), "the schedule")
                    self.notes.append(f"{DAY_NAMES[d.weekday()]}: {meal['name'].lower()} window is taken by {why}, "
                                      f"eat before or after")
            if meals and placed == 0 and local_at(d, parse_hhmm(meals[-1]["latest"], "meal"), tz) > self.now_m:
                self.notes.append(f"{DAY_NAMES[d.weekday()]}: no room for a meal inside your windows, eat between blocks")

        # free evening(s): pick the evenings with the least work due the next day
        n_free = self.p.get("floors", {}).get("free_evenings", 0)
        n_free -= sum(1 for i in kept_ids if i.startswith("free-evening-"))
        if n_free > 0:
            def pressure(d):
                nxt = local_at(d + timedelta(days=1), 24 * 60, tz)
                return sum(t["hours"] for t in tasks if local_at(d, 18 * 60, tz) <= t["due"] <= nxt)
            cands = [d for d in days if local_at(d, self.work_end, tz) > max(self.now_m, local_at(d, 18 * 60, tz))
                     and f"free-evening-{d.isoformat()}" not in kept_ids
                     and not any(k == "away" and overlap((s, e), (local_at(d, 18 * 60, tz), local_at(d, self.work_end, tz)))
                                 for s, e, _, k in self.occupied)]
            cands.sort(key=lambda d: (pressure(d), -d.weekday() if d.weekday() in (4, 5) else 0, d))
            for d in sorted(cands[:n_free]):
                s = max(local_at(d, 18 * 60, tz), self.now_m)
                e = local_at(d, self.work_end, tz)
                for fs, fe in list(free[d]):
                    if overlap((fs, fe), (s, e)):
                        free[d] = subtract(free[d], (s, e))
                blocks.append({"id": f"free-evening-{d.isoformat()}", "kind": "floor",
                               "title": "Free evening", "s": s, "e": e})

        # tasks: hours for this week (default allocation plus pulls), earliest deadline first,
        # spread over the days before each deadline instead of crammed into the first free morning
        overflow = []
        counter = {}
        for b in blocks:
            if b["kind"] == "task":
                n = int(b["id"].rsplit("#", 1)[-1]) if "#" in b["id"] else 0
                counter[b["task_id"]] = max(counter.get(b["task_id"], 0), n)
        def place_tasks(subset):
            for t in sorted(subset, key=lambda x: (x["due"], -x["score"])):
                due_soon = t["due"] <= week_end
                want = task_want[t["id"]] - kept_task.get(t["id"], 0)
                if want <= 0:
                    continue
                deadline = min(t["due"], week_end)
                start_floor = max(self.now_m, t["unlock"] or 0)
                ok_days = [d for d in days if local_at(d, self.wake, tz) < deadline and local_at(d, self.work_end, tz) > start_floor]
                lead = ok_days[-self.lead_days(t):]
                quota = max(60, int(math.ceil(want / max(1, len(lead)) / 30)) * 30)

                def place(d, limit):
                    nonlocal want
                    got_any = 0
                    for lo, hi in ((local_at(d, self.peak[0], tz), local_at(d, self.peak[1], tz)),
                                   (local_at(d, self.wake, tz), local_at(d, self.work_end, tz))):
                        while want > 0 and got_any < limit and focus_used[d] < self.focus:
                            chunk = min(want, MAX_CHUNK, limit - got_any, self.focus - focus_used[d])
                            need = min(MIN_CHUNK, want)
                            if chunk < need:
                                return
                            got = find(d, chunk, max(lo, start_floor), min(hi, deadline), need)
                            if not got:
                                break
                            if got[1] - got[0] > 30 and (got[1] - got[0]) % 30:
                                got = (got[0], got[0] + (got[1] - got[0]) // 30 * 30)
                            take(d, *got)
                            got_any += got[1] - got[0]
                            focus_used[d] += got[1] - got[0]
                            want -= got[1] - got[0]
                            counter[t["id"]] = counter.get(t["id"], 0) + 1
                            blocks.append({"id": f"{t['id']}#{counter[t['id']]}", "kind": "task",
                                           "title": f"{t['course']} {t['title']}".strip(), "s": got[0], "e": got[1],
                                           "task_id": t["id"], "score": t["score"], "due": t["due"],
                                           "url": t.get("url")})

                for d in lead:
                    if want <= 0:
                        break
                    place(d, quota)
                for d in ok_days:
                    if want <= 0:
                        break
                    place(d, MAX_TASK_PER_DAY)
                if want > 0:
                    overflow.append((t, want / 60, due_soon))

        urgent = [t for t in tasks if t["due"] <= self.now_m + 48 * 60]
        place_tasks(urgent)

        # goals, spread across days at preferred times
        late = from_min(self.now_m, tz).hour >= 19
        live_days = [d for d in days if cap[d] - used[d] >= 20 and not (late and d == self.today)]
        for g in sessions:
            have = kept_goal.get(g["id"], 0)
            n = min(g["count"] - have, len(live_days))
            if n < g["count"] - have:
                self.warnings.append(f"{g['name']}: only room for {n + have} of {g['count']} this week")
            if n <= 0:
                continue
            open_days = [d for d in live_days if d not in kept_days.get(g["id"], set())] or live_days
            picks = [open_days[min(len(open_days) - 1, round(i * len(open_days) / n))] for i in range(n)]
            used_days, placed = set(kept_days.get(g["id"], set())), 0
            taken_ids = {b["id"] for b in blocks}
            seq = 0
            pref = PEAKS.get(g.get("preferred") or "", None)
            for d in picks + live_days:
                if placed >= n:
                    break
                if d in used_days:
                    continue
                windows = []
                if pref:
                    windows.append((local_at(d, pref[0], tz), local_at(d, pref[1], tz)))
                windows.append((local_at(d, self.wake, tz), local_at(d, self.work_end, tz)))
                for lo, hi in windows:
                    got = find(d, g["minutes"], lo, hi, g["minutes"])
                    if got:
                        take(d, *got)
                        placed += 1
                        used_days.add(d)
                        seq += 1
                        while f"{slug(g['id'])}-{seq}" in taken_ids:
                            seq += 1
                        blocks.append({"id": f"{slug(g['id'])}-{seq}", "kind": g["kind"], "title": g["name"],
                                       "s": got[0], "e": got[1], "goal_id": g["id"]})
                        break
            if placed < n:
                self.warnings.append(f"{g['name']}: placed {placed} of {n} sessions")


        place_tasks([t for t in tasks if t not in urgent])
        return blocks, overflow, days, free, cap, used

    def run(self):
        tasks = self.tasks()
        demand, cap, goals, items, alloc, busy_drivers = self.radar(tasks)
        before = list(demand)
        radar = []
        counts = [len(x) for x in items]
        base = max(1, (counts[0] + counts[1]) / 2)
        active = {t["course"] for k in (0, 1) for t in items[k]}
        for k in range(4):
            status, ratio = self.status_for(before[k], cap[k])
            courses_here = {t["course"] for t in items[k]}
            partial = k >= 2 and counts[0] + counts[1] > 0 and (counts[k] < 0.5 * base or bool(active - courses_here))
            drivers = [t["title"] if t["course"] and t["course"] in t["title"] else f"{t['course']} {t['title']}".strip()
                       for t in sorted(items[k], key=lambda t: -t["hours"])[:3]]
            drivers += busy_drivers[k][:2]
            filled = min(8, max(0, round(min(ratio, 1) * 8)))
            label = status + (f" (only {counts[k]} item{'s' if counts[k] != 1 else ''} posted)" if partial else "")
            radar.append({"week": self.weeks[k].strftime("%b %-d"), "status": status, "hours_needed": round(before[k], 1),
                          "hours_free": round(cap[k], 1), "drivers": drivers, "partial": partial,
                          "bars": f"{self.weeks[k].strftime('%b %-d'):<7}{'━' * filled}{'░' * (8 - filled)} {label}"})
        pulls = self.future_pull(tasks, demand, cap, goals, alloc)
        for k in range(4):
            radar[k]["after_pull"] = self.status_for(demand[k], cap[k])[0]

        done_goals = dict(self.h.get("goal_done", {}).get(self.weeks[0].isoformat(), {}))
        for g, n in self.implicit["goals"].items():
            done_goals[g] = done_goals.get(g, 0) + n
        mode = "minimum" if self.minimum_forced else "normal"
        notes0, warn0 = list(self.notes), list(self.warnings)
        blocks, overflow, days, free, dcap, used = self.pack(tasks, alloc, mode == "minimum", done_goals)
        if any(due for _, _, due in overflow) and mode == "normal":
            first = (blocks, overflow, days, free, dcap, used, list(self.notes), list(self.warnings))
            self.notes, self.warnings = list(notes0), list(warn0)
            second = self.pack(tasks, alloc, True, done_goals)
            short = lambda ov: sum(h for _, h, due in ov if due)
            if short(second[1]) < short(overflow) - 0.25:
                mode = "minimum"
                blocks, overflow, days, free, dcap, used = second
            else:  # cutting goals would not save anything, keep the normal week
                blocks, overflow, days, free, dcap, used, self.notes, self.warnings = first
        for t, hrs, due_soon in overflow:
            if due_soon:
                self.warnings.append(f"{t['course']} {t['title']}: about {hrs:.1f}h won't fit before it's due")
            else:
                for p in pulls:
                    if p["task_id"] == t["id"] and p["to_week"] == self.weeks[0].strftime("%b %-d"):
                        p["hours"] = max(0, p["hours"] - hrs)
                pulls = [p for p in pulls if p["hours"] >= 0.5]

        planned = {b.get("task_id") for b in blocks if b["kind"] == "task"}
        seen = set()
        for t in tasks:
            if t["id"] in planned and t["course"] not in seen and (t["mult"] >= 1.25 or t["mult"] <= 0.8):
                if abs(t["hours"] - t["est"]) >= 1:
                    seen.add(t["course"])
                    self.notes.append(f"{t['course']} work has taken about {t['mult']:.1f}x the guess, "
                                      f"so {t['title']} is planned at {t['hours']:g}h")

        # buffer, fragility, fuel gaps
        fragile = []
        for d in days:
            day_blocks = [b for b in blocks if from_min(b["s"], self.tz).date() == d and b["kind"] == "task"]
            if not day_blocks:
                continue
            slack = length(free[d])
            if slack < FRAGILE_MIN:
                fragile.append({"day": DAY_NAMES[d.weekday()],
                                "reason": f"under {FRAGILE_MIN} min of slack, one late task breaks the evening"})
        for d in days:
            spans = sorted([(s, e) for s, e, _, k in self.occupied if from_min(s, self.tz).date() == d and k != "away"] +
                           [(b["s"], b["e"]) for b in blocks if from_min(b["s"], self.tz).date() == d and b["kind"] != "meal"])
            meals = [(b["s"], b["e"]) for b in blocks if b["kind"] == "meal" and from_min(b["s"], self.tz).date() == d]
            run_s = run_e = None
            for s, e in spans + [(10 ** 12, 10 ** 12)]:
                if run_e is not None and s - run_e <= 15:
                    run_e = max(run_e, e)
                    continue
                dn = DAY_NAMES[d.weekday()]
                if (run_s is not None and run_e - run_s > 5 * 60
                        and not any(overlap((ms, me), (run_s, run_e)) for ms, me in meals)
                        and not any(n.startswith(dn + ":") for n in self.notes)):
                    self.notes.append(f"{dn}: back to back {short_time(run_s, self.tz)} to "
                                      f"{short_time(run_e, self.tz)} with no meal, eat before it starts")
                run_s, run_e = s, e

        # lock-in: at most 3 per day, one call candidate
        for d in days:
            cands = [b for b in blocks if from_min(b["s"], self.tz).date() == d and b["kind"] in ("task", "goal")]
            cands.sort(key=lambda b: (-(b.get("score", 0) + (20 if b.get("due", 10 ** 12) - b["s"] < 24 * 60 else 0)), b["s"]))
            pick = cands[:3]
            for i, b in enumerate(pick):
                b["lock_in"] = True
                if i == 0:
                    b["call"] = True

        triage = None
        if mode == "minimum":
            wk_end = local_at(self.weeks[0] + timedelta(days=7), 0, self.tz)
            this_week = {b.get("task_id") for b in blocks if b["kind"] == "task"}
            ranked = sorted([t for t in tasks if t["id"] in this_week or t["due"] <= wk_end],
                            key=lambda t: (-(t["score"] + (15 if t["due"] <= wk_end else 0)), t["due"]))
            must = ranked[:3]
            slide = [t for t in ranked[3:] if t["prio"] < 3 and t["weight"] <= 5]
            triage = {
                "must_do": [{"task": f"{t['course']} {t['title']}".strip(), "due": fmt(t["due"], self.tz),
                             "why": self._why(t)} for t in must],
                "can_slide": [{"task": f"{t['course']} {t['title']}".strip(),
                               "why": f"worth {t['weight']:g}%" if t["weight"] else "low weight, not a North Star"}
                              for t in slide[:4]],
            }
            dropped = []
            for g in self.goal_sessions(False, 1.0, done_goals):
                lo = next((x for x in self.goal_sessions(True, 1.0, done_goals) if x["id"] == g["id"]), None)
                if not lo:
                    dropped.append(f"{g['name']} paused")
                elif lo["count"] < g["count"] or lo["minutes"] < g["minutes"]:
                    dropped.append(f"{g['name']} {g['count']}x to {lo['count']}x")
            if dropped:
                self.notes.insert(0, "minimum mode: " + ", ".join(dropped))

        blocks.sort(key=lambda b: b["s"])
        return {"radar": radar, "pulls": pulls, "mode": mode, "blocks": blocks, "fragile_days": fragile,
                "notes": self.notes, "warnings": self.warnings, "triage": triage, "days": days}

    def _why(self, t):
        bits = []
        if t["prio"] == 3:
            bits.append(f"{t['course']} is a North Star" + (f" ({t['star']})" if t["star"] else ""))
        if t["weight"]:
            bits.append(f"{t['weight']:g}% of the grade")
        if t["due"] - self.now_m < 48 * 60:
            bits.append("due within 48h")
        return ", ".join(bits) or "due soonest"


# ---------------------------------------------------------------- output

def render(result, planner):
    tz = planner.tz
    blocks = []
    for b in result["blocks"]:
        out = {"id": b["id"], "kind": b["kind"], "title": b["title"], "start": fmt(b["s"], tz), "end": fmt(b["e"], tz)}
        for k in ("lock_in", "call", "url", "task_id", "goal_id"):
            if b.get(k):
                out[k] = b[k]
        blocks.append(out)
    preview = []
    for d in result["days"]:
        day = [b for b in result["blocks"] if from_min(b["s"], tz).date() == d and b["kind"] in ("task", "goal", "floor")]
        if not day:
            continue
        parts, seen = [], set()
        for b in day:
            if b["title"] in seen:
                continue
            seen.add(b["title"])
            if b["title"] == "Free evening":
                parts.append("free evening")
                continue
            title = b["title"] if len(b["title"]) <= 30 else b["title"][:29] + "…"
            parts.append(f"{title} {short_time(b['s'], tz)}")
        more = f" +{len(parts) - 4} more" if len(parts) > 4 else ""
        preview.append(f"{DAY_NAMES[d.weekday()]}: " + ", ".join(parts[:4]) + more)
    out = {"tz": str(tz), "mode": result["mode"], "radar": result["radar"], "pulls": result["pulls"],
           "preview": "\n".join(preview[:8]), "fragile_days": result["fragile_days"], "notes": result["notes"][:6],
           "warnings": result["warnings"][:6], "blocks": blocks}
    if result["triage"]:
        out["triage"] = result["triage"]
    return out, blocks


def emit(data):
    def size():
        return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    # Cubbie reads the first 8,000 characters; trim the least useful parts first
    if size() > 7800:
        for b in data.get("blocks", []):
            for k in ("url", "task_id", "goal_id"):
                b.pop(k, None)
    if size() > 7800:
        for r in data.get("radar", []):
            for k in ("hours_needed", "hours_free"):
                r.pop(k, None)
        data["notes"] = data.get("notes", [])[:3]
    if size() > 7800:
        data["blocks"] = [b for b in data["blocks"] if b["kind"] != "meal"]
        data["meals_omitted"] = "run plan.py show for meal blocks"
    print(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


# ---------------------------------------------------------------- commands

def load_profile(sd):
    p = sd / "profile.json"
    if not p.exists():
        raise Fail(3, "no profile saved yet: run the first-time questions, then plan.py profile --file profile.json")
    return read_json(p)


def do_plan(sd, week, minimum, now=None, keep_past=None, keep=None, implicit=None):
    profile = load_profile(sd)
    validate_week(week)
    hist = load_history(sd)
    now_dt = parse_time(now or week["now"], "now")
    pl = Planner(profile, week, hist, now_dt, minimum, keep, implicit)
    result = pl.run()
    out, blocks = render(result, pl)
    saved = {"made": now_dt.isoformat(), "anchor": pl.weeks[0].isoformat(), "mode": result["mode"],
             "blocks": (keep_past or []) + blocks}
    return out, saved, pl


def cmd_profile(sd, args):
    if args.show:
        print(json.dumps(load_profile(sd), separators=(",", ":")))
        return
    if not args.file:
        raise Fail(2, "give --file profile.json or --show")
    p = read_json(args.file)
    validate_profile(p)
    wake = parse_hhmm(p.get("wake", "08:00"), "wake")
    sleep = parse_hhmm(p.get("sleep", "00:00"), "sleep")
    awake = ((sleep - wake) % (24 * 60)) or 24 * 60
    msg = {"saved": True, "goals": [g["name"] for g in p.get("goals", [])], "classes": len(p.get("classes", []))}
    need = p.get("floors", {}).get("sleep_hours")
    if need and 24 * 60 - awake < need * 60:
        msg["warning"] = f"wake {p.get('wake')} and sleep {p.get('sleep')} leave under {need}h of sleep"
    write_json(sd / "profile.json", p)
    print(json.dumps(msg, separators=(",", ":")))


def cmd_plan(sd, args):
    if not args.input:
        raise Fail(2, "give --input week.json")
    week = read_json(args.input, what="week.json")
    out, saved, _ = do_plan(sd, week, args.minimum)
    write_json(sd / "week.json", week)
    write_json(sd / "plan.json", saved)
    emit(out)


def cmd_replan(sd, args):
    if not (sd / "week.json").exists() or not (sd / "plan.json").exists():
        raise Fail(5, "no saved week yet: run plan.py plan --input week.json first")
    week = read_json(sd / "week.json")
    old = read_json(sd / "plan.json")
    now = args.now or week["now"]
    now_dt = parse_time(now, "--now")
    now_m = to_min(now_dt)
    hist = load_history(sd)
    status = {e["block"]: e["status"] for e in hist["log"] if e.get("block")}
    tz = get_tz(load_profile(sd), now_dt)

    def mins(b, key):
        return to_min(datetime.strptime(b[key], "%Y-%m-%d %H:%M").replace(tzinfo=tz))

    same_week = Planner(load_profile(sd), week, hist, now_dt).weeks[0].isoformat() == old.get("anchor")
    past, keep = [], []
    implicit = {"goals": {}, "task_hours": {}}
    for b in old["blocks"] if same_week else []:
        st = status.get(b["id"])
        if mins(b, "end") <= now_m or st == "done":
            past.append(b)
            if st is None:  # not logged: assume it happened
                if b.get("goal_id"):
                    implicit["goals"][b["goal_id"]] = implicit["goals"].get(b["goal_id"], 0) + 1
                if b.get("task_id"):
                    h = (mins(b, "end") - mins(b, "start")) / 60
                    implicit["task_hours"][b["task_id"]] = implicit["task_hours"].get(b["task_id"], 0) + h
        elif st != "skipped" and mins(b, "start") >= now_m:
            kb = dict(b)
            kb["s"], kb["e"] = mins(b, "start"), mins(b, "end")
            keep.append(kb)
    week["now"] = now
    out, saved, pl = do_plan(sd, week, args.minimum, now, past, keep, implicit)
    old_future = {b["id"]: b for b in old["blocks"] if b not in past and mins(b, "start") >= now_m}
    new_future = {b["id"]: b for b in out["blocks"]}
    moved = [{"title": b["title"], "from": old_future[i]["start"], "to": b["start"]}
             for i, b in new_future.items() if i in old_future and old_future[i]["start"] != b["start"]]
    added = [{"title": b["title"], "start": b["start"]} for i, b in new_future.items()
             if i not in old_future and b["kind"] != "meal"]
    removed = [{"title": b["title"], "was": b["start"]} for i, b in old_future.items()
               if i not in new_future and b["kind"] != "meal"]
    out["changes"] = {"moved": moved[:8], "added": added[:8], "removed": removed[:8],
                      "mode_was": old.get("mode"), "mode_now": out["mode"], "kept_past": len(past)}
    write_json(sd / "week.json", week)
    write_json(sd / "plan.json", saved)
    emit(out)


def cmd_add(sd, args):
    if not (sd / "week.json").exists():
        raise Fail(5, "no saved week yet: run plan.py plan --input week.json first")
    item = read_json(args.file)
    week = read_json(sd / "week.json")
    items = item if isinstance(item, list) else [item]
    added = []
    for it in items:
        if "due" in it:
            validate_task(it, "item")
            week.setdefault("tasks", [])
            week["tasks"] = [t for t in week["tasks"] if t["id"] != it["id"]] + [it]
            added.append({"task": it["title"]})
        elif "start" in it:
            validate_busy(it, "item")
            week.setdefault("busy", []).append(it)
            added.append({"busy": it["title"]})
        else:
            raise Fail(2, "item needs either due (a task) or start and end (an event)")
    write_json(sd / "week.json", week)
    print(json.dumps({"added": added, "next": "run plan.py replan --now <local time>"}, separators=(",", ":")))


def cmd_log(sd, args):
    hist = load_history(sd)
    week = read_json(sd / "week.json") if (sd / "week.json").exists() else {"tasks": []}
    tasks = {t["id"]: t for t in week.get("tasks", [])}
    mult = hist.setdefault("multipliers", {})
    entry = {"status": args.status}
    if args.block:
        if not (sd / "plan.json").exists():
            raise Fail(5, "no saved plan yet")
        plan = read_json(sd / "plan.json")
        b = next((x for x in plan["blocks"] if x["id"] == args.block), None)
        if not b:
            raise Fail(4, f"no block {args.block}; run plan.py show for ids")
        s = datetime.strptime(b["start"], "%Y-%m-%d %H:%M")
        e = datetime.strptime(b["end"], "%Y-%m-%d %H:%M")
        planned = (e - s).seconds / 3600
        entry.update({"block": b["id"], "kind": b["kind"], "planned_hours": round(planned, 2), "day": b["start"][:10]})
        if args.status == "done":
            if b.get("task_id"):
                tid = b["task_id"]
                hist["task_done_hours"][tid] = hist["task_done_hours"].get(tid, 0) + planned
                course = tasks.get(tid, {}).get("course")
                if args.actual_hours and course and planned > 0:
                    old = mult.get(course, 1.0)
                    raw = args.actual_hours / planned * old
                    mult[course] = round(max(0.5, min(3.0, 0.5 * old + 0.5 * raw)), 2)
                    entry["multiplier"] = mult[course]
            if b.get("goal_id") or b["kind"] in ("goal", "floor"):
                gid = b.get("goal_id") or b["title"]
                anchor = plan.get("anchor")
                wk = hist["goal_done"].setdefault(anchor, {})
                wk[gid] = wk.get(gid, 0) + 1
    elif args.task:
        t = tasks.get(args.task)
        if not t:
            raise Fail(4, f"no task {args.task} in the saved week")
        entry["task"] = args.task
        if args.status == "done":
            if args.task not in hist["task_complete"]:
                hist["task_complete"].append(args.task)
            course, est = t.get("course"), float(t.get("estimate_hours", 0) or 0)
            if args.actual_hours and course and est > 0:
                old = mult.get(course, 1.0)
                mult[course] = round(max(0.5, min(3.0, 0.5 * old + 0.5 * (args.actual_hours / est))), 2)
                entry["multiplier"] = mult[course]
    else:
        raise Fail(2, "give --block <id> or --task <id>")
    if args.actual_hours:
        entry["actual_hours"] = args.actual_hours
    hist["log"].append(entry)
    hist["log"] = hist["log"][-400:]
    write_json(sd / "history.json", hist)
    print(json.dumps({"logged": entry, "next": "run plan.py replan --now <local time> if the plan should move"},
                     separators=(",", ":")))


def cmd_show(sd, args):
    if not (sd / "plan.json").exists():
        raise Fail(5, "no saved plan yet: run plan.py plan --input week.json first")
    plan = read_json(sd / "plan.json")
    rows = [f"{b['id']} | {b['kind']} | {b['title']} | {b['start'][5:]}-{b['end'][11:]}" for b in plan["blocks"]]
    print(f"plan made {plan['made']} mode {plan['mode']}\n" + "\n".join(rows))


def cmd_radar(sd, args):
    if not (sd / "week.json").exists():
        raise Fail(5, "no saved week yet: run plan.py plan --input week.json first")
    week = read_json(sd / "week.json")
    out, _, _ = do_plan(sd, week, False, args.now)
    print(json.dumps({"radar": out["radar"], "pulls": out["pulls"]}, ensure_ascii=False, separators=(",", ":")))


def cmd_stats(sd, args):
    hist = load_history(sd)
    streak = {}
    for anchor, goals in sorted(hist.get("goal_done", {}).items()):
        for g, n in goals.items():
            streak.setdefault(g, []).append(f"{anchor}: {n}")
    print(json.dumps({"multipliers": hist.get("multipliers", {}), "goal_sessions_by_week": streak,
                      "logged": len(hist.get("log", []))}, separators=(",", ":")))


def seed_sample(sd, command):
    shutil.copy(SKILL_DIR / "assets" / "sample_profile.json", sd / "profile.json")
    if command not in ("plan", "profile"):
        week = read_json(SKILL_DIR / "assets" / "sample_week.json")
        _, saved, _ = do_plan(sd, week, False)
        write_json(sd / "week.json", week)
        write_json(sd / "plan.json", saved)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Oh Shift! planner")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("profile", "plan", "replan", "add", "log", "show", "radar", "stats"):
        sp = sub.add_parser(name)
        sp.add_argument("--sample", action="store_true", help="use bundled sample data in a throwaway folder")
        if name == "profile":
            sp.add_argument("--file")
            sp.add_argument("--show", action="store_true")
        if name == "plan":
            sp.add_argument("--input")
            sp.add_argument("--minimum", action="store_true")
        if name == "replan":
            sp.add_argument("--now")
            sp.add_argument("--minimum", action="store_true")
        if name == "radar":
            sp.add_argument("--now")
        if name == "add":
            sp.add_argument("--file", required=True)
        if name == "log":
            sp.add_argument("--block")
            sp.add_argument("--task")
            sp.add_argument("--status", choices=["done", "skipped"], required=True)
            sp.add_argument("--actual-hours", type=float)
    args = ap.parse_args(argv)
    sd = state_dir(args.sample)
    try:
        if args.sample:
            seed_sample(sd, args.command)
            if args.command == "plan":
                args.input = str(SKILL_DIR / "assets" / "sample_week.json")
            if args.command == "profile" and not args.show:
                args.file = str(SKILL_DIR / "assets" / "sample_profile.json")
        {"profile": cmd_profile, "plan": cmd_plan, "replan": cmd_replan, "add": cmd_add, "log": cmd_log,
         "show": cmd_show, "radar": cmd_radar, "stats": cmd_stats}[args.command](sd, args)
    except Fail as f:
        print(f"error: {f}", file=sys.stderr)
        return f.code
    finally:
        if args.sample:
            shutil.rmtree(sd, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
