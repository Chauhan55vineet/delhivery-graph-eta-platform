# Delhivery Platform — GitHub + Render Deployment Guide
**Owner:** Vineet Chauhan | **Version:** 1.0.0

> This is the complete step-by-step roadmap to push `delhivery_graph_platform` to GitHub and auto-deploy it on [Render.com](https://render.com) as a live public URL.

---

## Step 0: Install Git for Windows (one-time, if not already done)

1. Download **Git for Windows** from [https://git-scm.com/download/win](https://git-scm.com/download/win)
2. Run the installer. Accept all defaults.
3. Verify installation — open a new PowerShell window and run:
   ```powershell
   git --version
   # Expected: git version 2.x.x.windows.x
   ```

---

## Step 1: Configure Git Identity (one-time)

Open PowerShell and run:
```powershell
git config --global user.name "Vineet Chauhan"
git config --global user.email "your-email@example.com"
```

---

## Step 2: Create the GitHub Repository

1. Go to [https://github.com/new](https://github.com/new)
2. Fill in:
   - **Repository name:** `delhivery-graph-eta-platform`
   - **Description:** `Graph-Enhanced ETA & Network Intelligence Platform for Delhivery Operations`
   - **Visibility:** ✅ Public *(required for Render free tier)*
   - **Initialize repository:** ❌ Leave unchecked (we push our own code)
3. Click **Create repository**
4. Copy the **HTTPS URL** shown on the next page — it will look like:
   ```
   https://github.com/YourUsername/delhivery-graph-eta-platform.git
   ```

---

## Step 3: Initialize Git in the Project Folder

Open PowerShell and run these commands **exactly in order**:

```powershell
# Navigate to the project folder
cd "C:\Users\Vineet Chauhan\Downloads\DELHIVERY\delhivery_graph_platform"

# Initialize a new git repository
git init

# Set the default branch name to 'main' (matches GitHub's default)
git branch -M main

# Add the GitHub remote  ← paste YOUR repo URL here
git remote add origin https://github.com/YourUsername/delhivery-graph-eta-platform.git

# Stage all files
git add .

# Verify what will be committed (should NOT include delivery_data.csv or __pycache__)
git status
```

---

## Step 4: Make the First Commit & Push

```powershell
# Commit everything
git commit -m "Initial release: Graph-Enhanced ETA Platform v1.0.0

- FastAPI app serving /predict, /health, dashboard, hubs, corridors, FTL-Carting advisor
- 5-screen frontend SPA (Dashboard, ETA Predictor, Bottleneck Map, FTL vs Carting, Strategy Memo)
- Pre-trained HistGradientBoostingRegressor artifacts (MAE 33.6 min, 43.9% within 15%)
- render.yaml, Procfile, Dockerfile for one-click Render deployment
- GitHub Actions CI workflow (.github/workflows/ci.yml)"

# Push to GitHub
git push -u origin main
```

If prompted for credentials, sign in with your GitHub username + a **Personal Access Token (PAT)**:
- Go to GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
- Click **Generate new token** → scope: `repo` → copy the token
- Use it as your **password** when git prompts

---

## Step 5: Deploy on Render.com

### 5.1 Create a Render Account
Go to [https://render.com](https://render.com) and sign up (free). Connect your GitHub account when prompted.

### 5.2 Create a New Web Service
1. Click **New → Web Service**
2. Select **"Build and deploy from a Git repository"**
3. Click **"Connect"** next to `delhivery-graph-eta-platform`
4. Render will **auto-detect** your `render.yaml` and pre-fill everything — verify the fields:

   | Field | Value |
   |:---|:---|
   | **Name** | `delhivery-graph-eta` |
   | **Region** | Singapore (closest to India) |
   | **Branch** | `main` |
   | **Runtime** | Python 3 |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
   | **Plan** | Free (or Starter for always-on) |

5. Under **Environment Variables**, confirm:
   - `ARTIFACT_DIR` = `./artifacts`
   - `PYTHON_VERSION` = `3.11.0`

6. Click **Create Web Service**

### 5.3 Wait for Build (~3–5 minutes)
Render will:
1. Clone your GitHub repo
2. Run `pip install -r requirements.txt` (installs FastAPI, scikit-learn, pandas, etc.)
3. Start `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Run the health check at `/health`

Watch the **Logs** tab — you should see:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:10000
```

### 5.4 Your Live URL
Once deployed, Render gives you a public URL like:
```
https://delhivery-graph-eta.onrender.com
```

Test it immediately:
```bash
curl https://delhivery-graph-eta.onrender.com/health
# {"status":"ok","model_trained_at":"2026-09-27T01:22:51","held_out_mae_minutes":33.6,...}

curl -X POST https://delhivery-graph-eta.onrender.com/predict \
  -H "Content-Type: application/json" \
  -d '{"source_center":"IND000000ACB","destination_center":"IND842001AAA","osrm_time":19.0,"osrm_distance":11.9653,"actual_distance_to_destination":10.4356,"route_type":"Carting","pickup_datetime":"2026-09-27T14:30:00"}'
```

---

## Step 6: Auto-Redeploy on Every Push (Already Configured)

By default, Render auto-redeploys whenever you push to `main`. So the workflow for future updates is:

```powershell
# Make changes to app.py / static/index.html / artifacts/
git add .
git commit -m "Update: describe your change here"
git push origin main
# → Render automatically detects the push and rebuilds
```

---

## Step 7: Free Tier Considerations

> [!IMPORTANT]
> On Render's **free tier**, the service **spins down after 15 minutes of inactivity**. The first request after inactivity will take ~30 seconds (cold start). This is fine for demos and ops reviews.
>
> Upgrade to **Starter (\$7/month)** to get **always-on** with no cold starts if this becomes a production operational tool.

To avoid cold starts on the free tier, you can ping the health endpoint periodically using a free service like [UptimeRobot](https://uptimerobot.com):
- Monitor URL: `https://delhivery-graph-eta.onrender.com/health`
- Interval: Every 5 minutes
- This keeps the service warm indefinitely for free.

---

## Step 8: Connect Your Custom Domain (Optional)

1. In Render dashboard → your service → **Settings** → **Custom Domains**
2. Add your domain (e.g., `eta.delhivery-ops.com`)
3. Update your DNS provider with the CNAME Render provides

---

## All Deployment Files Summary

| File | Purpose |
|:---|:---|
| [`render.yaml`](./render.yaml) | Declarative Render service config (auto-detected) |
| [`Procfile`](./Procfile) | Fallback start command for Render |
| [`Dockerfile`](./Dockerfile) | Container build (Python 3.11-slim, scipy-ready) |
| [`.python-version`](./.python-version) | Pins Python 3.11.0 for Render's build system |
| [`requirements.txt`](./requirements.txt) | All production dependencies |
| [`.gitignore`](./.gitignore) | Excludes `__pycache__`, `.env`, `delivery_data.csv` |
| [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) | GitHub Actions: runs API smoke tests on every push |
