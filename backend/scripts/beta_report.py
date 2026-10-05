"""Small operator report for a closed Beta. Reads only the local ICE-800 database."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import db, init_db  # noqa: E402

init_db()
with db() as con:
    users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    profiles = con.execute("SELECT cohort,onboarding_completed_at FROM beta_profiles").fetchall()
    connections = con.execute("SELECT COUNT(*) c FROM connections").fetchone()["c"]
    feedback = con.execute("SELECT feedback_type,rating,message,created_at FROM beta_feedback ORDER BY id DESC").fetchall()

completed = sum(1 for p in profiles if p["onboarding_completed_at"])
ratings = [f["rating"] for f in feedback if f["rating"] is not None]
print(f"ICE-800 Beta report\nUsers: {users}\nOnboarding complete: {completed}/{len(profiles)}\nConnections: {connections}\nFeedback: {len(feedback)}")
if ratings:
    print(f"Average rating: {sum(ratings)/len(ratings):.2f}/5")
print("Feedback types:", dict(Counter(f["feedback_type"] for f in feedback)))
for f in feedback[:10]:
    print(f"- [{f['feedback_type']}] {f['created_at']}: {f['message'][:180]}")
