"""End-to-end: onboarding → sandbox channel → trend discovery → script → originality → SEO → voice →
visuals → FFmpeg render → QA → approval → (sandbox) upload → analytics → optimization."""
from sqlalchemy import select

from app.models import AnalyticsSnapshot, PublishingJob, Video, WorkflowRun
from app.workers import jobs
from app.workflows import pipeline


def onboard(c):
    ch = c.post("/api/v1/channels/connect", json={"mode": "sandbox", "title": "Space Facts Lab"}).json()
    r = c.patch(f"/api/v1/channels/{ch['id']}", json={
        "niches": ["science-technology"],
        "settings": {"language": "en", "short_duration_seconds": 15, "publish_times": ["09:00", "18:30"],
                     "timezone": "Asia/Kolkata", "video_quality": "720p"},
        "brand": {"brand_name": "Space Facts Lab", "primary_color": "#1D4ED8"},
    })
    assert r.status_code == 200, r.text
    r = c.post("/api/v1/onboarding/complete", json={"budget_mode": "free", "monthly_budget_usd": 0, "activate": False, "confirm": True})
    assert r.status_code == 200, r.text
    return ch["id"]


def test_onboarding_requires_confirmation_and_niche(admin):
    ch = admin.post("/api/v1/channels/connect", json={"mode": "sandbox"}).json()
    r = admin.post("/api/v1/onboarding/complete", json={"confirm": True})
    assert r.status_code == 400 and "niche" in r.json()["detail"]
    admin.patch(f"/api/v1/channels/{ch['id']}", json={"niches": ["history"]})
    assert admin.post("/api/v1/onboarding/complete", json={"confirm": False}).status_code == 400
    assert admin.post("/api/v1/onboarding/complete", json={"confirm": True}).status_code == 200


def test_full_pipeline_sandbox(admin, db):
    channel_id = onboard(admin)

    # Trend discovery (offline sources → evergreen mock topics) + scoring
    stats = jobs.scan_trends(channel_id, force=True)
    assert stats[channel_id]["stored"] > 0
    trends = admin.get(f"/api/v1/trends?channel_id={channel_id}").json()
    assert trends and all(0 <= t["score"] <= 100 for t in trends)
    assert trends[0]["score_breakdown"]["weights"]["view_velocity"] == 0.25

    # Approve a topic → production run (manual topic so research matches our fixture)
    r = admin.post("/api/v1/content/generate", json={"channel_id": channel_id, "topic": "The Moon", "format": "short",
                                                     "review_script": True})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    run = pipeline.advance(db, run_id)
    assert run.status == "waiting_approval" and run.current_step == "script_review", run.last_error
    detail = admin.get(f"/api/v1/content/{run_id}").json()
    assert detail["script"] and len(detail["scenes"]) >= 3
    assert detail["sources"][0]["url"].startswith("https://en.wikipedia.org")

    # Edit a scene in the studio, then approve the script
    first = detail["scenes"][1]
    assert admin.patch(f"/api/v1/content/{run_id}", json={"scenes": [{"id": first["id"], "on_screen_text": "Edited text"}]}).status_code == 200
    assert admin.post(f"/api/v1/content/{run_id}/script-decision", json={"approve": True}).status_code == 200

    db.expire_all()
    run = pipeline.advance(db, run_id)
    assert run.status == "waiting_approval" and run.current_step == "approval", run.last_error
    video = db.get(Video, run.video_id)
    assert video.status == "awaiting_approval"
    assert video.qa_report["passed"], video.qa_report
    assert video.width == 720 and video.height == 1280
    assert run.steps["originality"]["status"] == "done"
    prov = admin.get(f"/api/v1/content/{run_id}").json()["provenance"]
    assert prov and all(p["license"]["verified"] for p in prov)
    assert any(p["kind"] == "music" for p in prov)

    # Media is served only to signed-in users
    assert admin.get(f"/api/v1/media/{video.file_path}").status_code == 200

    # Human approval → upload (sandbox) as private
    approvals = admin.get("/api/v1/approvals").json()
    assert len(approvals) == 1
    r = admin.post(f"/api/v1/approvals/{approvals[0]['id']}/decide", json={"approve": True, "privacy": "private"})
    assert r.status_code == 200, r.text
    db.expire_all()
    run = pipeline.advance(db, run_id)
    assert run.status == "succeeded", run.last_error
    video = db.get(Video, run.video_id)
    assert video.youtube_video_id.startswith("sandbox-") and video.status == "uploaded"
    hist = admin.get(f"/api/v1/publishing/history?video_id={video.id}").json()
    assert {"queued", "uploaded"} <= {h["event"] for h in hist}

    # Idempotency: re-executing the job never uploads twice
    job = db.scalar(select(PublishingJob).where(PublishingJob.video_id == video.id))
    from app.agents.publishing import execute_job
    assert execute_job(db, job).youtube_video_id == video.youtube_video_id

    # Analytics + optimisation loop
    jobs.collect_analytics(force=True)
    assert db.scalar(select(AnalyticsSnapshot).where(AnalyticsSnapshot.video_id == video.id)) is not None
    insights = jobs.weekly_optimize(force=True)
    assert insights["videos_analyzed"] == 1
    dash = admin.get("/api/v1/dashboard").json()
    assert dash["videos_published"] == 1 and dash["videos_generated"] == 1


def test_resume_does_not_regenerate_assets(admin, db):
    channel_id = onboard(admin)
    run_id = admin.post("/api/v1/content/generate", json={"channel_id": channel_id, "topic": "The Moon",
                                                          "review_script": False}).json()["run_id"]
    run = pipeline.advance(db, run_id)
    assert run.status == "waiting_approval", run.last_error
    voice_out = run.steps["voice"]["output"]
    assert voice_out["generated"] > 0
    # Re-render from the voice step: all voice + images must be reused.
    admin.post("/api/v1/videos/render", json={"run_id": run_id})
    db.expire_all()
    run = pipeline.advance(db, run_id)
    assert run.steps["voice"]["output"]["generated"] == 0 and run.steps["voice"]["output"]["reused"] == voice_out["generated"]
    assert run.steps["visuals"]["output"]["generated"] == 0


def test_rejected_video_is_not_uploaded(admin, db):
    channel_id = onboard(admin)
    run_id = admin.post("/api/v1/content/generate", json={"channel_id": channel_id, "topic": "The Moon",
                                                          "review_script": False}).json()["run_id"]
    pipeline.advance(db, run_id)
    appr = admin.get("/api/v1/approvals").json()[0]
    admin.post(f"/api/v1/approvals/{appr['id']}/decide", json={"approve": False, "note": "not good enough"})
    db.expire_all()
    run = pipeline.advance(db, run_id)
    assert run.status == "failed"
    assert db.scalar(select(PublishingJob)) is None
    assert db.get(WorkflowRun, run_id).last_error.startswith("approval")
