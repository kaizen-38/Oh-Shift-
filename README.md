# Oh Shift!

Oh Shift! sees your “Oh Sh*t!” week before you do. It catches the deadline pileups before they catch you, shifts the chaos early, and when life inevitably goes off-script, one text gets you back to “we ball.”

A [Cubbie](https://cubbie.ai) Skill for the Cubbie Hackathon, Track 1.

## Install

Text this link to Cubbie in iMessage:

```
https://github.com/kaizen-38/Oh-Shift-
```

Then text "plan my week". Nothing to sign up for and no API keys: it uses the Canvas and Google Calendar you've already connected to Cubbie.

## What it does

Most planners answer "what should I do this week?". Oh Shift! also answers "which week is going to wreck me, and what can I do about it now?"

- **Storm Radar.** A load forecast for the next 4 weeks from your Canvas deadlines, class schedule and goals. It names the bad week and what makes it bad.
- **Future Pull.** When a storm is coming, work that's already posted moves into a lighter week before it hits.
- **A real week plan.** Homework, workouts, sports and meals packed into calendar blocks, with slack left in every day. Goes on your Google Calendar after you say yes.
- **One text replans.** "skipped gym", "that homework took 5 hours", "flying home Thursday". Only what's affected moves.
- **Minimum Viable Week.** Tell it what keeps you sane (7h sleep, 2 workouts, two meals, one free evening). In a crunch week, goals shrink to that minimum. They never disappear.
- **North Stars.** "A- in CSE 310" or "internship recruiting". Tradeoffs follow what matters to you, not just due dates.
- **Lock-In.** A text when a key block starts. If you opt in and don't answer, Cubbie calls.
- **Panic mode.** "I'm drowning" gets you the 3 things that actually matter this week, what can slide, and what stays protected.
- Works by voice: "Hey Siri, text Cubbie I skipped the gym today."

## What it looks like

```
Next 4 weeks:
Oct 26 ━━░░░░░░ light
Nov 2  ━━━░░░░░ light
Nov 9  ━━━━━━━░ storm
Nov 16 ━░░░░░░░ light (only 1 item posted)

Nov 9 is the problem: CSE 310 Project 3, CSE 310 Midterm 2, ENG 301 Essay 2, plus your internship interview.

Pulling 3.5h of Project 3 into this week while you have room.

Mon: Calisthenics 8a, Call parents 9a, Run 5p
Tue: STP 420 Homework 6 8a
Wed: Calisthenics 8a, STP 420 Homework 6 9a, CSE 310 Quiz 7 12:15p, CSE 310 Project 3 2:20p +1 more
Thu: ENG 301 Reading response 5 8a, CSE 310 Project 3 10:15a
Fri: Calisthenics 8a, ENG 301 Reading response 5 9a, CSE 310 Project 3 10a
Sat: Calisthenics 8a, CSE 340 Lab 4 9a, CSE 310 Project 3 2p, Run 5p +1 more
Sun: CSE 340 Lab 4 8a

Put this week on your calendar?
```

The radar bars, the pull and the week lines are the real output of the bundled sample week (`python3 scripts/plan.py plan --sample`); Cubbie writes the sentences around them.

## How it works

Cubbie brings the abilities; the Skill brings the know-how and the math.

- `SKILL.md` tells Cubbie when to run, what to ask (about 2 minutes, once), what to fetch from Canvas and Google Calendar, how to text the results, and when to ask before acting.
- `scripts/plan.py` does the forecasting and packing so the same inputs always give the same plan. Python standard library only, nothing to install.
  - Each assignment's hours are spread over the days before it's due and summed per week. Capacity is your realistic daily focus hours, limited by the time left after classes, fixed activities, events, meals, goals and a 15% buffer.
  - Storm is over 85% of capacity. Future Pull moves posted work into the lightest earlier week until the storm is down to about 75%.
  - Packing places urgent work first, then goals at your preferred times, then the rest in 1 to 2 hour blocks before each deadline.
  - Replans keep every block where it was unless it now conflicts.
  - Reality Check learns how long each course's work really takes you and plans with that.

## Privacy and safety

- Your profile and plan stay in your own Cubbie workspace (`~/.config/oh-shift/`). Nothing is sent anywhere else.
- Nothing goes on your calendar, and no reminder or call is set up, until you say yes.
- Fitness goals count sessions, not your body. It never sets weight, calorie or diet targets.
- It never invents due dates or free time. If a week can't fit, it says so.

## Try it on Cubbie

1. Text the repo link to Cubbie and say yes to installing it.
2. In a new message: "plan my week". It asks a few setup questions, then sends the radar and the week.
3. Try "what do the next few weeks look like" and "when is my worst week".
4. Say yes to the calendar. Check the blocks landed.
5. Text "skipped gym today, move it". Only the gym block should move.
6. Text "I'm drowning this week". You should get 3 must-dos, what can slide, and what's protected.
7. Try it without Canvas connected: it should ask what's due instead of stopping.
8. Accept the Sunday check-in and confirm it's scheduled.
9. Next day, new conversation: "plan my week" again. It shouldn't re-ask the setup questions.

## Development

```bash
python3 scripts/plan.py plan --sample      # full plan from the bundled sample week
python3 scripts/plan.py radar --sample     # just the 4-week radar
python3 -m unittest discover tests         # tests
```

`--sample` runs in a throwaway folder and never touches saved state.
