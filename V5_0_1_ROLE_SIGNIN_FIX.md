# AI Tutor v5.0.1 Role Sign-in Fix

Version 5.0.1 makes the role-based portals visible before authentication.

## Changes

- Adds separate **Administrator sign in**, **Lecturer sign in**, and **Student sign in** tabs.
- Keeps **Student registration** and **First administrator** as separate setup actions.
- Verifies that the account role matches the selected sign-in tab.
- Opens the correct portal immediately after successful sign-in.
- Displays clearer instructions for lecturer credentials created by an administrator.
- Refreshes the application shell cache so browsers receive the corrected interface.

## Lecturer workflow

1. An administrator signs in through **Administrator sign in**.
2. The administrator creates a lecturer account and gives the lecturer the temporary credentials.
3. The lecturer selects **Lecturer sign in** and enters those credentials.
4. The lecturer changes the temporary password when prompted.
5. The lecturer portal opens, where courses, enrolment codes and teaching documents are managed.
