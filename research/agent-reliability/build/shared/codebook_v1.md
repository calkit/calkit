# Codebook

Data from a randomized trial of a 12-week computerized cognitive training
program in older adults, recruited at four community centers (sites A–D).

## participants.csv

One row per enrolled participant, from the enrollment database.

| Column           | Description                                                  |
| ---------------- | ------------------------------------------------------------ |
| `participant_id` | Site letter and three-digit number, e.g., `A-014`            |
| `site`           | Recruiting site: `A`, `B`, `C`, or `D`                       |
| `enrolled_on`    | Enrollment date                                              |
| `arm`            | Randomized arm: `training` or `control` (waitlist)           |
| `age`            | Age in years at enrollment (eligible range 60–85)            |
| `sex`            | `F` or `M`                                                   |
| `education`      | Highest education: `secondary`, `college`, or `graduate`     |

## sessions.csv

One row per assessment session, exported from the sites' tablet apps.
Participants are assessed at baseline (week 0) and at weeks 4, 8, and 12.

| Column           | Description                                                  |
| ---------------- | ------------------------------------------------------------ |
| `participant_id` | Participant identifier                                       |
| `week`           | Assessment week: 0, 4, 8, or 12                              |
| `session_date`   | Date of the session                                          |
| `form`           | Test form administered: `A` or `B`                           |
| `status`         | `complete`, or `incomplete` if stopped early (not scored)    |
| `score`          | Cognitive composite score; blank when incomplete             |
