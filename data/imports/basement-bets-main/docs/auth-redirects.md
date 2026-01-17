# Supabase Auth Redirect Strategy

Configuring Supabase Auth to work across dynamic Vercel Preview URLs and Localhost without manual intervention.

## The Challenge
Vercel Preview deployments generate unique URLs (e.g., `*-preview.vercel.app`). Supabase Auth needs to know which URLs are "safe" to redirect to after a successful login or email confirmation.

## Recommended Configuration

### 1. Supabase Dashboard Settings
In your Supabase Project (STAGING and PROD separately):
1. Navigate to **Authentication** -> **URL Configuration**.
2. **Site URL**:
    - **PROD**: `https://basement-bets.vercel.app`
    - **STAGING**: `https://basement-bets-staging.vercel.app` (or your chosen stable preview domain).
3. **Redirect URLs** (Allow List):
    - `http://localhost:3000/**`
    - `https://*-preview.vercel.app/**` (Wildcard support for Vercel)
    - `https://basement-bets.vercel.app/**`

### 2. Next.js / React Callback Logic
When calling `signInWithOAuth` or `signInWithOtp`, dynamically determine the `redirectTo` URL based on the current window location.

```javascript
const getURL = () => {
  let url =
    process.env.NEXT_PUBLIC_SITE_URL ?? // Set this for prod
    process.env.NEXT_PUBLIC_VERCEL_URL ?? // Automatically set on Vercel
    'http://localhost:3000/';
  // Make sure to include `https://` when not localhost.
  url = url.includes('http') ? url : `https://${url}`;
  // Make sure to include a trailing `/`.
  url = url.charAt(url.length - 1) === '/' ? url : `${url}/`;
  return url;
};

// Usage
await supabase.auth.signInWithOAuth({
  provider: 'google',
  options: {
    redirectTo: `${getURL()}auth/callback`,
  },
});
```

---

## Troubleshooting
- **Invalid Redirect URL**: Double-check that the URL (including port and protocol) exactly matches an entry in the Supabase Redirect Allow List.
- **Preview Callback**: Ensure `NEXT_PUBLIC_VERCEL_URL` is enabled in your Vercel Project Settings (it is by default).
