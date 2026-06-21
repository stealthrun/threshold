# Worked example: `faded_vo2`

This is the signature read — the one that shows the difference between describing a
session and interpreting it. It's also a frozen [golden](../evals/) the system is graded
against.

## The session

A VO2 interval session: `6 x 800m`, planned at `3:05/km`.

| rep | pace | heart rate |
|----|------|-----------|
| 1 | 3:04/km | 172 |
| 2 | 3:07/km | 175 |
| 3 | 3:12/km | 176 |
| 4 | 3:19/km | 177 |
| 5 | 3:25/km | 177 |
| 6 | 3:25/km | 178 |

The athlete's max heart rate is **192**. Their note: *"legs cooked by rep 4, lungs still
had room."*

## What the data says — and what it means

The pace bled away across the reps (3:04 → 3:25), but heart rate climbed to ~177 and
**stalled there, 15 beats under max**. The legs reached their limit before the
cardiovascular system reached its ceiling. So the *intended* stimulus — maxing out the
aerobic engine — was only partly delivered. The session looks hard (RPE 8) but didn't do
the job it was prescribed for. For this athlete, whose limiter is aerobic durability, that
distinction is the entire point.

## Description vs interpretation

> **Analyst (what most tools produce):**
> "38% of time in Z5. Pace decoupled in the back half, dropping 21s/km from rep 1 to rep
> 6. Average HR 170, pacing consistency 0.71."

Every word true. None of it tells the athlete what happened or what to do. It also leaks
exactly the things the [voice guard](../skills/coaching-interpretation/scripts/coach_voice.py) forbids — `Z5`, `38%`, `0.71`,
`decoupled`.

> **Coach (what `threshold` targets):**
> "Your legs gave out before your heart did. The pace fell away through the back half
> while your effort flattened out well under your ceiling, so you didn't get the full
> engine stimulus this session was meant for. That's not lost fitness, it's the legs
> tapping out early. Next VO2 set, cut it to four reps and hold the pace honestly rather
> than grinding out faded ones."

Same data. The second version names the mechanism, places it against this athlete's
limiter, and ends on one concrete change.

## How the gate scores it

- **`must_address`:** pace faded across the reps · heart rate stayed below max so the
  cardiovascular stimulus was diminished · the legs reached their limit before the heart.
- **`must_not`:** call it simply "a hard day" without naming the diminished stimulus ·
  read the fade as a heart/aerobic *ceiling* being hit (it wasn't — that's the opposite
  read).
- **voice guard:** the coach version above passes with zero violations.
