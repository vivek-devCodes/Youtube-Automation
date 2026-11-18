# Google & YouTube setup

You need this only to work with a **real** channel. Sandbox channels work without it.

## 1. Create a Google Cloud project
1. Open https://console.cloud.google.com/ → project picker → **New project** (e.g. "ai-youtube-studio").
2. **APIs & Services → Library**: enable **YouTube Data API v3** and **YouTube Analytics API**.

## 2. OAuth consent screen
1. **APIs & Services → OAuth consent screen** (Google Auth Platform → Branding/Audience).
2. User type **External**. Fill in the app name and your support email.
3. Scopes: `.../auth/youtube.upload`, `.../auth/youtube.readonly`, `.../auth/yt-analytics.readonly`.
4. While the app is in **Testing**, add your Google account under **Test users**.
   - Testing-mode refresh tokens expire after **7 days**, so you will need to reconnect weekly. Publishing the app ("In production") removes this limit, but Google may require verification for sensitive scopes.
   - Unverified apps' uploads may be locked to private until the API project passes Google's audit. Request one with the [YouTube API audit form](https://support.google.com/youtube/contact/yt_api_form) if uploads stay private.

## 3. OAuth client
1. **Credentials → Create credentials → OAuth client ID → Web application**.
2. **Authorized redirect URI**, which must exactly match `PUBLIC_BASE_URL` + `/api/v1/auth/youtube/callback`:
   - local dev: `http://localhost:3000/api/v1/auth/youtube/callback`
   - Docker: `http://localhost/api/v1/auth/youtube/callback`
   - production: `https://your-domain.com/api/v1/auth/youtube/callback`
3. Copy the client ID and secret into `.env`:
   ```
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=....
   ```
4. Restart the backend. **Connect with Google** becomes active.

## 4. API key for trend discovery (recommended)
**Credentials → Create credentials → API key** → restrict it to *YouTube Data API v3* → `YOUTUBE_API_KEY=...`.

## Quota
Default quota is 10,000 units/day per project. Approximate costs: `videos.list` 1, `search.list` 100, `videos.insert` 1,600 (verify in your console and set `YOUTUBE_UPLOAD_QUOTA_COST`), `thumbnails.set` 50. A trend scan of one niche uses ~102 units; one upload uses ~1,650. The dashboard shows today's usage. When quota runs out, uploads are deferred 6 hours rather than failing.

## Other limits worth knowing
- **Custom thumbnails** require a phone-verified channel (https://www.youtube.com/verify). Otherwise the upload still succeeds and the thumbnail step is logged as failed.
- The API **cannot create channels** or change channel art. Do those in YouTube Studio.
- Shorts are detected by YouTube from the vertical aspect ratio and a duration ≤ 3 minutes. `#Shorts` in the description helps.
