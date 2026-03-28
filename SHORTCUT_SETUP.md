# iOS 26 Shortcut Setup Guide

This guide walks you through creating an iOS 26 Shortcut that automatically logs your Apple Watch workouts to your GitHub profile.

## Prerequisites

- iPhone running iOS 26
- Apple Watch paired and logging workouts to Health
- GitHub Personal Access Token (PAT) with `repo` scope

## Step 1: Create a GitHub Personal Access Token

1. Go to **GitHub.com > Settings > Developer settings > Personal access tokens > Fine-grained tokens**
2. Click **Generate new token**
3. Name it `workout-shortcut`
4. Set **Repository access** to **Only select repositories** and pick `areporeporepo/areporeporepo`
5. Under **Permissions > Repository permissions**, set **Actions** to **Read and write**
6. Click **Generate token** and copy it — you'll need it in the Shortcut

## Step 2: Build the iOS 26 Shortcut

Open the **Shortcuts** app and create a new shortcut called **"Log Workout"**.

Add these actions in order:

### Action 1: Find Health Samples

- Action: **Find Health Samples**
- Type: **Workouts**
- Sort by: **End Date (Latest First)**
- Limit: **1**
- Save result as: `Workout`

### Action 2: Get Details of Workout

You need several "Get Details" actions to extract each field:

**2a.** Get **Type** of `Workout` → save as `WorkoutType`

**2b.** Get **Duration** of `Workout` → save as `Duration`

**2c.** Get **Active Energy** of `Workout` → save as `Calories`

**2d.** Get **Average Heart Rate** of `Workout` → save as `HeartRate`

**2e.** Get **Distance** of `Workout` → save as `Distance`

**2f.** Get **End Date** of `Workout` → save as `WorkoutDate`

### Action 3: Format Date

- Action: **Format Date**
- Date: `WorkoutDate`
- Format: **Custom** → `yyyy-MM-dd'T'HH:mm:ss`
- Save as: `FormattedDate`

### Action 4: Round Values

**4a.** Round `Duration` to **Ones Place** → save as `RoundedDuration`

**4b.** Round `Calories` to **Ones Place** → save as `RoundedCalories`

**4c.** Round `HeartRate` to **Ones Place** → save as `RoundedHR`

**4d.** Round `Distance` to **Hundredths** → save as `RoundedDistance`

### Action 5: Convert Distance to Kilometers

- Action: **Measurement > Convert**
- Convert `RoundedDistance` to **Kilometers**
- Save as: `DistanceKM`

*(Skip this if your Health app already reports in km)*

### Action 6: Get Contents of URL (GitHub API Call)

This is the core action that triggers the GitHub Actions workflow:

- Action: **Get Contents of URL**
- URL: `https://api.github.com/repos/areporeporepo/areporeporepo/actions/workflows/log-workout.yml/dispatches`
- Method: **POST**
- Headers:
  - `Authorization`: `Bearer YOUR_GITHUB_TOKEN_HERE`
  - `Accept`: `application/vnd.github.v3+json`
  - `Content-Type`: `application/json`
- Request Body (JSON):

```json
{
  "ref": "main",
  "inputs": {
    "workout_type": "WorkoutType",
    "duration_minutes": "RoundedDuration",
    "calories_burned": "RoundedCalories",
    "heart_rate_avg": "RoundedHR",
    "distance_km": "DistanceKM",
    "date": "FormattedDate"
  }
}
```

**Important:** In Shortcuts, replace the quoted values above with the actual Shortcut variables (tap the field and select the variable from the magic variable list).

### Action 7 (Optional): Show Notification

- Action: **Show Notification**
- Title: `Workout Logged!`
- Body: `WorkoutType — RoundedDuration min, RoundedCalories cal`

## Step 3: Set Up the Automation Trigger

This is what makes it fully automatic — no taps needed after your workout.

1. Go to **Shortcuts > Automation** tab
2. Tap **+ New Automation**
3. Scroll down and tap **Apple Watch Workout**
4. Select **Workout Ends** (any type, or pick specific ones)
5. Choose **Run Immediately** (iOS 26 allows this without confirmation)
6. Select your **"Log Workout"** shortcut
7. Done!

## How It Works End-to-End

```
Apple Watch workout ends
        ↓
iOS detects workout completion (Health automation)
        ↓
Shortcut runs automatically
        ↓
Reads latest workout from Health
        ↓
Calls GitHub API (workflow_dispatch)
        ↓
GitHub Actions workflow runs
        ↓
Workout data saved to data/workouts.json
        ↓
README.md updated with latest stats
        ↓
Your GitHub profile shows live health data!
```

## Troubleshooting

### Shortcut doesn't trigger automatically
- Make sure **Run Immediately** is selected in the automation (iOS 26 feature)
- Check that the Shortcuts app has Health permissions: **Settings > Privacy > Health > Shortcuts**

### GitHub API returns 404
- Verify your token has `Actions: Read and write` permission on this repo
- Make sure the workflow file is committed to the `main` branch
- Check the URL matches your exact repo name

### Workout data is wrong
- The shortcut reads the **most recent** workout. If you do back-to-back workouts, the second one may overwrite timing
- Heart rate and distance may be `null` for some workout types (e.g., strength training typically has no distance)

### Token security
- Store your GitHub token using Shortcuts' built-in "Text" action at the top of the shortcut
- Alternatively, store it in a secure note and use "Find Notes" to retrieve it
- Never share screenshots of your shortcut that show the token
- Use a **fine-grained token** with minimal permissions (only Actions on this repo)

## Optional: Sleep & Other Health Data

You can duplicate this pattern for other health data:

- **Sleep:** Create a similar shortcut triggered by "Sleep > Wake Up" automation
- **Steps:** Run on a daily schedule shortcut that reads step count
- **Weight:** Trigger when a new weight sample is logged

Just create additional workflow dispatch inputs and extend the Python script!
