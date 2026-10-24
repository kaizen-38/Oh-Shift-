---
name: oh-shift
description: Plans the student's week and forecasts the next four, spotting the week that will crush them and pulling work earlier, while protecting workouts, sports, meals and sleep. Use when the student asks to plan their week, wants a Sunday reset or says "oh shift", asks what the next few weeks look like or when their worst week is, asks how to fit the gym, a sport, calisthenics, running or any goal around assignments, says they skipped something or a task ran long, mentions a trip or new event, or says they are overwhelmed, behind or drowning. Also use for texts dictated through Siri or voice notes about their schedule. Unlike study-plan-builder, it plans school and personal goals together, forecasts load weeks ahead and moves work before a heavy week hits, keeps a minimum set of non-negotiables during crunch weeks, and can call the student when a key block starts.
---

# Oh Shift!

Oh Shift! sees the student's worst week coming before they do. It looks a month ahead, spots where exams, deadlines,
work and life are about to collide, and starts shifting things early. When life happens, one text moves only what
is affected.

Most planners answer "what should I do this week?". Oh Shift! also answers "which week is going to wreck me, and
what can I do about it now?".

Every week (Sunday evening by default) the student gets:

- **Storm Radar.** A load forecast for the next 4 weeks, built from Canvas deadlines, the class schedule and their
  goals. It names the heavy week and what makes it heavy.
- **Future Pull.** When a storm is coming, work that is already posted moves into the lighter weeks before it.
- **A week plan.** Homework, workouts, sports, other goals and meals packed into calendar blocks, with slack left
  in every day, sent to Google Calendar after the student says yes.

During the week, one text ("skipped gym", "that homework took 5 hours", "flying home Friday") reshuffles only what
is affected.

Three ideas run through everything:

- **North Stars.** What the student is aiming for this semester (an A- in CSE 310, internship recruiting, a half
  marathon on March 14). Tradeoffs follow these, not just due dates.
- **Minimum Viable Week.** The few things that keep the student functional even in the worst week (7h sleep, a
  workout 2x, two meals a day, one free evening). The plan never goes below them.
- **Buffer.** About 15% of each day stays unplanned, so one task running late doesn't break the evening.

Cubbie abilities used: Canvas, Google Calendar, memory, reminders and scheduled check-ins (including phone calls),
files and photos (a class schedule screenshot), voice-note transcription. Sign-in: only accounts already connected
to Cubbie. No API keys and no packages.

The forecasting and packing math lives in `scripts/plan.py` (Python standard library only), so the same inputs
give the same plan. The script cannot reach Canvas or the calendar: Cubbie fetches that data first and passes it
in a file. The script keeps its state (profile, saved week, last plan, history) in `$SKILL_DATA_DIR` when it is
set, otherwise in `~/.config/oh-shift/`.

## When to use

- "plan my week" / "sunday reset" / "oh shift" / "what does my week look like"
- "when is my worst week?" / "what do the next few weeks look like"
- "I want to hit the gym 4x a week and still get my CSE homework done"
- "I have intramural soccer Tuesday nights and want to do calisthenics 3x too"
- "skipped gym today, move it" (often dictated: "Hey Siri, text Cubbie skipped gym today")
- "the stats homework took way longer than I thought"
- "I'm flying home Thursday night"
- "I'm drowning this week"

Do not use it for a pure exam-review plan with no personal goals (that is study-plan-builder), or for anything that
submits work or emails someone.

## Replies

- Short, plain text, no Markdown. Most replies fit on one phone screen.
- One idea per message. Lead with the answer.
- The radar is 4 lines, one per week, using the `bars` text the script prints, for example:
  Oct 26 ━━━━░░░░ ok
  Nov 2  ━━━━━━░░ busy
  Nov 9  ━━━━━━━━ storm
  Nov 16 ━━░░░░░░ light (only 2 items posted)
- A week preview is at most 7 short lines (one per day). The full block list goes on the calendar, not in a text.
- Ask one question at a time and offer a default the student can accept with "yes".
- When something moved, say what moved and why in one line: "Moved Thu gym to Wed 7am, Thursday is your flight."
- Texts from Siri or voice notes can contain transcription mistakes. If a course or task name is unclear, ask once
  instead of guessing.
- Do not show the student internal numbers (load percentages, buffer hours, priority scores) unless they ask.

## 1. First time: learn the student's semester (about 2 minutes)

Skip any question the student already answered or that Cubbie already remembers. Ask one at a time, each with a
default:

1. **Class schedule.** First look in the student's Google Calendar for recurring events that match their Canvas
   course names. If they are there, confirm in one line and move on. If not: "Send me a screenshot of your class
   schedule, or just list it (CSE 310 MW 10:30-11:45...)." Read it and confirm the list back in one message.
2. **North Stars.** "Anything you're aiming for this semester? Like an A- in a class, internship recruiting, a race."
   For each course they name, note the target and whether it is high, normal or low priority. Courses they don't
   name are normal.
3. **Goals.** "What do you do to stay active, or want to do more of?" Anything counts: gym, calisthenics, running,
   climbing, yoga, pickup soccer, an intramural team, dance. Also non-fitness goals (reading, a side project,
   practicing an instrument). For each, ask whether it is:
   - **flexible** (can go any time, like the gym or calisthenics): how often and how long. Default "4x a week,
     60 min?"
   - **fixed** (set times, like an intramural game or a club practice): the days and times.
   Fixed activities are protected like classes and never moved. Note any goal with a date (a race, a book by
   December).
4. **Minimum Viable Week.** "On a brutal week, what can't drop?" Default: "7h sleep, your main workout 2x, lunch and
   dinner, one free evening. Sound right?" Ask whether fixed activities (a team game) are in the minimum too;
   default yes, since missing a team game lets other people down.
5. **Day shape.** Wake time, sleep time, no-work-after time, best focus time (morning, afternoon or night), and
   how many hours of schoolwork they can do in a day before they're fried. Default: 8 am, midnight, 11 pm,
   morning, 5 hours.
6. **Lock-In.** "Want a text when key blocks start? I can also call you if you don't answer." Options: off, text,
   call. Default: text.

Before asking, check both places the profile can be: Cubbie's memory and `python3 scripts/plan.py profile --show`
(exit code 3 means none is saved). If either has it, use it and do not ask again, even in a new conversation.

Remember the answers with Cubbie's memory and save them for the script, so the profile survives if either copy is
reset. When the student mentions a change later ("I quit running", "new job Saturdays"), update both right away
instead of re-asking everything. Write `profile.json`:

```json
{
  "timezone": "America/Phoenix",
  "wake": "08:00", "sleep": "00:00", "no_work_after": "23:00", "peak": "morning",
  "max_focus_hours": 5,
  "buffer_pct": 15,
  "lock_in": "text",
  "classes": [
    {"title": "CSE 310", "days": ["Mon", "Wed"], "start": "10:30", "end": "11:45",
     "from": "2026-08-20", "until": "2026-12-05"}
  ],
  "north_stars": [
    {"course": "CSE 310", "target": "A-", "priority": "high"},
    {"name": "Internship recruiting", "priority": "high"},
    {"name": "Half marathon", "date": "2027-03-14", "goal": "run"}
  ],
  "goals": [
    {"id": "calisthenics", "name": "Calisthenics", "type": "flexible", "per_week": 4, "minutes": 60,
     "preferred": "morning"},
    {"id": "run", "name": "Run", "type": "flexible", "per_week": 3, "minutes": 40, "preferred": "morning"},
    {"id": "intramural", "name": "Intramural soccer", "type": "fixed",
     "sessions": [{"day": "Tue", "start": "20:00", "end": "21:00"}]}
  ],
  "floors": {
    "sleep_hours": 7,
    "goals": {"calisthenics": {"per_week": 2, "minutes": 30}, "run": {"per_week": 1, "minutes": 25},
              "intramural": {"keep": true}},
    "meals": [
      {"name": "Lunch", "earliest": "11:30", "latest": "14:00", "minutes": 30},
      {"name": "Dinner", "earliest": "18:00", "latest": "20:30", "minutes": 30}
    ],
    "free_evenings": 1,
    "custom": [{"name": "Call parents", "per_week": 1, "minutes": 20}]
  }
}
```

Then run `python3 scripts/plan.py profile --file profile.json`. When anything changes later, edit and run it again.

Fitness goals are about showing up, not about the body. Do not set weight, calorie or diet targets, and do not
count calories or comment on food, even if asked; meals are in the plan only so they happen. If the student says
they are sick, injured or exhausted, offer to turn that day's goal into rest and do not argue.

## 2. The weekly reset

Run this when the student asks, and from the Sunday check-in.

1. Gather, in the student's time zone:
   - Google Calendar events for the next 28 days (work, plans, trips). Leave out events this Skill created, which
     have `oh-shift` in their description. Classes come from the profile, so skip calendar events that are
     the same classes.
   - Canvas assignments due in the next 28 days that are not submitted: course, title, due time, points, the
     assignment group weight when Canvas returns it, and the unlock date when there is one.
   If Canvas is not connected, ask the student to connect it, or ask them to list what is due in the next two weeks,
   and go on. If Google Calendar is not connected, go on without it; the plan is sent as a PDF and an .ics file
   instead of calendar events.
2. Ask one question: "Anything coming up Canvas doesn't know about? Exams, trips, interviews?" Default: "nope".
   Many exams and outside platforms (Gradescope, WebAssign, publisher sites) never show up in Canvas, so this
   question matters. Add what they say to `tasks` (exams) or `busy` (trips, interviews).
3. Write `week.json` with the student's local date and time (the sandbox clock may be in another time zone):

```json
{
  "now": "2026-10-25T19:00:00-07:00",
  "busy": [{"title": "Flight home", "start": "2026-10-29T18:00:00-07:00",
            "end": "2026-11-01T14:00:00-07:00", "away": true}],
  "tasks": [
    {"id": "canvas-12345", "title": "Homework 6", "course": "STP 420",
     "due": "2026-10-28T23:59:00-07:00", "unlock": "2026-10-21T00:00:00-07:00",
     "estimate_hours": 3, "weight_pct": 4, "url": "https://canvas.asu.edu/courses/1/assignments/12345"},
    {"id": "exam-cse310-mid2", "title": "CSE 310 Midterm 2", "course": "CSE 310",
     "due": "2026-11-10T10:30:00-07:00", "kind": "exam", "estimate_hours": 8, "weight_pct": 20}
  ]
}
```

   Estimate `estimate_hours` when the student did not say: quiz 1, homework 3, essay 5, project milestone 6,
   exam 6 to 10 by weight. The script adjusts these with what it learned (section 5). Do not invent `weight_pct`;
   leave it out when Canvas doesn't give it.
4. Run `python3 scripts/plan.py plan --input week.json`. It prints JSON with:
   - `radar`: one entry per week for 4 weeks with `status` (`light`, `ok`, `busy`, `storm`) before any pulls,
     `after_pull` (the status once Future Pull moved work), `bars` (the text bar), `drivers` (the items and events
     that make it heavy) and `partial` (true when the week looks light because little is posted yet)
   - `pulls`: work moved earlier to soften a storm: `task`, `course`, `hours`, `what` (`review`, `a first part`
     or `all of it`), `from_week`, `to_week`
   - `blocks`: this week's plan (`kind` is `task`, `goal`, `meal` or `floor`), each with an `id`, `start` and `end`
     in the student's local time (`tz`), `lock_in` true on the few blocks worth a reminder, `call` true on the one
     block per day worth a call, and the Canvas `url` for task blocks when there is one
   - `mode`: `normal`, or `minimum` when the week only fits at the Minimum Viable Week
   - `fragile_days`: days where the slack is too thin, with one plain reason each
   - `notes`: what changed and why (minimum mode, meals that could not fit, back-to-back stretches, Reality Check)
   - `warnings`: deadlines at risk, floors that could not be met
   - `preview`: a ready week preview, one line per day
5. Text in this order, as separate short messages:
   1. The radar (4 lines), plus one line naming the storm week and its drivers, if there is one:
      "Nov 9 is the problem: CSE 310 midterm, STP project, internship interview."
   2. The pulls, in one or two lines: "Pulling your STP project outline into Thursday while you have room."
   3. The week preview. If `mode` is `minimum`, say so in one line and list what changed:
      "This week only fits in minimum mode: gym 4 to 2, reading paused. Wednesday night stays free."
   4. One line for the most fragile day, if any: "Thursday fits, but one late task breaks your evening."
   5. "Put this week on your calendar?"
6. Only after the student says yes, create one Google Calendar event per block. Title: the block title. Description: `oh-shift <block id>`, plus the Canvas link for task blocks. Then set up Lock-In
   (section 4) if the student chose text or call.
7. The first time, offer the weekly check-in: "Want this every Sunday? 7 pm?" Create it only after a yes, worded so
   it makes sense on its own: "Oh Shift weekly reset: run the 4-week radar and plan the student's next 7 days with
   the oh-shift Skill."

### How the script decides (for answering "why?")

- **Load.** Each task's hours are spread over the days before it is due (2 to 4 days for homework, a week for
  exams), and summed per week. Capacity is the student's daily focus hours, limited by the free time left after
  classes, fixed activities, events, meals, goals and the buffer.
- **Storm.** A week whose load is over 85% of its capacity. Busy is over 70%.
- **Partial.** A later week is marked partial when it has fewer than half the items of the first two weeks, or a
  course that had work in those weeks has none yet.
- **Future Pull.** For a storm week, it moves work into the lightest earlier week until the storm is down to about
  75%, starting with high-priority North Star courses and the heaviest items. It only pulls work that already
  exists: posted assignments (after their unlock date), exam review, and the first half of a big project. It never
  schedules work on an assignment that is not posted yet.
- **Priority.** Each task's priority comes from its North Star (high, normal, low), its weight in the course, and
  how close it is. Due date alone never decides.
- **Minimum Viable Week.** If the week does not fit, goals drop to their floors before any floor is touched.
  Floors (sleep, meals, minimum goals, free evenings) are never removed; if the week still does not fit, the
  overflow goes into `warnings` instead.
- **Fixed activities** (an intramural game, a club practice) are placed at their set times like classes. In
  minimum mode they stay unless the student left them out of the floors; the plan works around them.
- **Placement.** Work due within 48 hours is placed first, then goals at their preferred times, then the rest,
  spread over the days before each deadline in 1 to 2 hour blocks, best focus time first.
- **Buffer.** `buffer_pct` of each day's waking hours stays unplanned. A day is fragile when its slack falls under
  45 minutes.

## 3. Midweek replan

Use when the student reports a change: skipped a block, finished early, a task ran long, a new task, a trip, a
cancelled class, feeling sick.

1. Log what happened, one command per item:
   - Done: `python3 scripts/plan.py log --block <id> --status done [--actual-hours <h>]`
   - Skipped: `python3 scripts/plan.py log --block <id> --status skipped`
   - A whole assignment finished: `python3 scripts/plan.py log --task <task id> --status done [--actual-hours <h>]`
   Blocks that already ended and were not logged count as done, so only log what the student tells you about.
   - A new task or event: add it with `python3 scripts/plan.py add --file new.json` (same shape as an entry in
     `tasks` or `busy`).
   Match the student's words to block ids from the current plan (`python3 scripts/plan.py show` prints it). If two
   blocks could match, ask which.
2. Run `python3 scripts/plan.py replan --now "<local ISO time>"`. It reuses the saved week data, re-checks the
   radar, and keeps every future block where it was unless it now conflicts or is no longer needed. It prints the
   full plan plus `changes`: `moved`, `added` and `removed` (meals left out), and `mode_was` / `mode_now`.
3. Text only the changes, at most 4 lines: "Moved gym to Wed 7am. Homework 6 now Tue 2-5pm." If the replan
   created a new storm or switched to minimum mode, say that first. Ask "Update your calendar?" and, after a yes,
   change only those events and their Lock-In reminders.

## 4. Lock-In

Respect the student's level (off, text, call). Remind only on blocks the script marked `lock_in` (at most 3 a day,
ranked by North Star priority, grade weight and anything due within 24 hours). Never call during sleep hours,
classes or busy events, and never call for a meal.

For each `lock_in` block, after the student approved the plan, create:

1. A reminder 10 minutes before, worded to make sense on its own:
   "Oh Shift: <block title> starts at <time>. Reply 'on it', 'skip' or 'move'."
2. Only at level call, and only for the block marked `call` (one a day): a scheduled check-in 10 minutes
   after it starts: "Oh Shift lock-in for <block title> at <time>: if the student has not replied since the
   reminder at <reminder time>, call them. Keep the call under 30 seconds: say what the block is and ask if they are
   starting. If they say skip or move, log it with the oh-shift Skill and replan."

When the student replies "skip", log it and offer the replan. When they reply "move", ask "When? Tonight 8pm?".

## 5. Reality Check (quiet)

When the student mentions how long something took ("took 4h", "that was quick"), log it with `--actual-hours`, on
the block, or on the task if they mean the whole assignment.
Do not ask after every task. The script keeps a smoothed multiplier per course and applies it to later estimates.
Mention it only when it changes a plan by an hour or more: "Your STP homework has taken about 1.5x my guess, so I
planned 4.5h." `python3 scripts/plan.py stats` prints the multipliers if the student asks.

## 6. Panic mode

When the student says they are overwhelmed, drowning, behind or can't do it all:

1. One line of acknowledgment, no lecture.
2. Run `python3 scripts/plan.py replan --now "<local ISO time>" --minimum`. It switches to the Minimum Viable Week
   and adds `triage`: `must_do` (the top 3 of this week's work by North Star priority, weight and due time, each
   with `why`) and `can_slide` (low-weight work outside the North Stars, each with `why`).
3. Text the top 3 must-dos, then what can slide and why: "This 2% quiz can wait. Your CSE 310 project can't, it's
   your A- class."
4. Text what stays protected: "Sleep, both meals and Wednesday night are still in."
5. If a deadline is at risk, offer to draft an extension email to the professor (Cubbie's email-to-professor Skill
   drafts it; the student sends it).
6. Ask "Update your calendar?" as in section 3.

If the student's message suggests they are in crisis rather than just busy, stop planning and respond to that first.

## When something fails

| Exit code | Meaning | What to do |
| --- | --- | --- |
| 2 | `week.json`, `profile.json` or the added item is invalid | Fix the field the error names and run once more |
| 3 | No profile saved | Run the first-time questions (section 1) |
| 4 | Unknown block or task id | Run `show` and match again, or ask the student which block |
| 5 | No saved week or plan yet | Run the weekly reset (section 2) first |

- The week is truly overbooked even at the minimum: the plan still comes back, with the overflow in `warnings`.
  Say so honestly and offer panic mode. Never invent free time.
- If `partial` is true for a week, say it may look lighter than it is. Never call a week safe just because little
  is posted.
- Use only dates and times that Canvas, the calendar or the student gave. Never guess a due date or an exam date.
- If the script fails twice, tell the student in one line and offer a plain-text plan of the top 3 tasks and their
  floors for tomorrow.

## Script reference

| Command | Does |
| --- | --- |
| `plan.py profile --file profile.json` | Save classes, North Stars, goals, floors and preferences |
| `plan.py profile --show` | Print the saved profile (exit 3 if none) |
| `plan.py plan --input week.json` | Radar for 4 weeks, Future Pull, and this week's blocks |
| `plan.py replan --now <time> [--minimum]` | Repack from now with the saved data, print the diff |
| `plan.py add --file item.json` | Add a task or busy event to the saved week |
| `plan.py log --block <id> --status done/skipped [--actual-hours h]` | Record what happened to a block |
| `plan.py log --task <id> --status done [--actual-hours h]` | Record a whole assignment as finished |
| `plan.py show` | Print the current plan with block ids |
| `plan.py radar` | Print only the 4-week radar from the saved data |
| `plan.py stats` | Print per-course multipliers and goal sessions per week |
| any command with `--sample` | Use `assets/sample_profile.json` and `assets/sample_week.json` and leave the student's state alone |
