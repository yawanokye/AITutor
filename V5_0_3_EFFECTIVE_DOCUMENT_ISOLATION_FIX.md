# AI Tutor v5.0.3 Effective Document Isolation Fix

Version 5.0.3 revisits document deletion and ownership after field testing showed that some older administrator uploads could remain visible and some delete actions appeared to have no effect.

## Root causes corrected

1. Older class-less uploads did not always use the newer `global::` source-name prefix. The previous administrator delete endpoint rejected those legacy records.
2. Document ownership was inferred only from `class_id`. Version 5.0.3 adds an explicit repository scope to every indexed extract.
3. Older browser assets could remain active after deployment, making the interface call an outdated delete workflow.
4. Course deletion removed the current source identifier but could leave historical index aliases created by older releases.

## New ownership rules

Every indexed extract is now classified as one of:

- `admin_private`, visible only to administrators
- `course`, visible only inside the exact lecturer-owned course
- `shared`, reserved for a future deliberately shared institutional repository

At application startup, every historical record is migrated automatically:

- blank `class_id` becomes `admin_private`
- non-blank `class_id` becomes `course`

Administrator-private content is never included in lecturer or student retrieval.

## Effective deletion

Administrator deletion now:

- accepts both new and legacy source identifiers
- checks that the source belongs to the private administrator repository
- deletes every indexed extract for that source
- returns the number of extracts removed
- refreshes the repository after deletion

Lecturer course-document deletion now removes:

- the course-document record
- all parsed sections and subsections
- the current index source
- historical source aliases associated with the same document, filename and course

## Browser refresh protection

Versioned assets have been moved to `5.0.3`. The root page and API responses now use `Cache-Control: no-store`, while JavaScript and CSS use revalidation headers. The service-worker cache name is also changed so the previous interface is removed during activation.

## Deployment

1. Back up the existing PostgreSQL database.
2. Upload the contents of the v5.0.3 patch to the repository root.
3. Commit to `main`.
4. In Render, choose **Manual Deploy → Clear build cache and deploy**.
5. Wait until the service is Live.
6. Open `/health` and confirm version `5.0.3`.
7. Sign out and sign in again.
8. Refresh once with `Ctrl + Shift + R`.

No manual SQL migration or new environment variable is required.
