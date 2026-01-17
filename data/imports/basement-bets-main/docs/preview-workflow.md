# Preview & Deployment Workflow

This workflow ensures that every change is validated in a production-like environment (Preview) before hitting live users.

## 1. Local Development
1. Run `npm run dev` and `uvicorn src.api:app --reload`.
2. Verify changes against the **STAGING** database.
3. Run `npm run preflight` to check linting and basic tests.

## 2. Push to Branch
1. Commit changes to a feature branch: `git checkout -b feature/new-analytics`.
2. Push to GitHub/Vercel: `git push origin feature/new-analytics`.
3. Vercel automatically creates a **Preview Deployment**.

## 3. Preview Validation
1. Open the Vercel Preview URL.
2. Verify that the "STAGING" banner appears in the UI.
3. Perform functional testing (Login, Paste Slip, Analytics).
4. Share the URL with coordinates for peer review.

## 4. Production Release
1. Open a Pull Request to `main`.
2. Once approved, merge the PR.
3. Vercel deploys to **Production**.
4. Verify the live site (ensure no "Staging" banner is visible).

---

## Preflight Checklist
Execute before pushing:
- [ ] `npm run lint`: No styling or syntax errors.
- [ ] `npm run test`: All unit tests pass.
- [ ] `npm run build`: Frontend build succeeds locally.
- [ ] `python3 -m pytest`: Backend tests pass.
