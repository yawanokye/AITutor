# Fix for Render's one-free-database limit

This package uses a web-service-only `render.yaml`. It does not try to create a second Render Postgres database.

## Deploy

1. Replace the old repository contents with this fixed package, or at minimum replace `render.yaml` and `app/knowledge.py`.
2. Commit and push the changes.
3. In Render, open the failed Blueprint and click **Manual Sync**, or create a new Blueprint from the repository.
4. When Render requests environment-variable values, enter:
   - `OPENAI_API_KEY`: your OpenAI API key
   - `DATABASE_URL`: the **Internal Database URL** of your existing Render Postgres database
5. Deploy the Blueprint.
6. Open the generated web service and check `/health`.

## Finding the existing database URL

Open the existing database in Render, choose **Connect**, and copy **Internal Database URL**. The web service and database should be in the same Render account and region. If they are not, use the External Database URL instead.

## What the tutor adds to the existing database

The app creates only one table named `ai_tutor_knowledge_chunks`. It does not delete or alter other application tables.

## Alternatives

- Delete the existing free database only if it is no longer needed, then use `render-new-database.yaml` as the Blueprint path.
- Upgrade the new database definition in `render-new-database.yaml` from `plan: free` to a paid Render Postgres plan.
- Leave `DATABASE_URL` empty for a quick test. The app will use local JSON storage, but uploaded course materials can disappear when a free Render service restarts or redeploys.
