// Identity-provider library templates — shared between the admin "Add provider"
// modal and the settings page that consumes a picked template. Kept in a plain
// module (not inside an SFC <script setup>, which cannot have named exports).

export interface IdpTemplate {
  key: string
  name: string
  type: string
  logo: string
  issuerPattern: string
  scopes: string[]
  groupClaim: string
  // Library grouping: 'social' (Google + OIDC providers), 'directory' (LDAP/AD),
  // 'provisioning' (SCIM). Used to render the three sections in the library modal.
  group?: 'social' | 'directory' | 'provisioning'
}

export const IDP_TEMPLATES: IdpTemplate[] = [
  // ── SOCIAL / OIDC ──────────────────────────────────────────────────────────
  { key: 'google', name: 'Google', type: 'OIDC', logo: 'google', issuerPattern: 'https://accounts.google.com', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'microsoft', name: 'Microsoft / Entra', type: 'OIDC', logo: 'microsoft', issuerPattern: 'https://login.microsoftonline.com/{tenant}/v2.0', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'okta', name: 'Okta', type: 'OIDC', logo: 'okta', issuerPattern: 'https://{your-domain}.okta.com', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'auth0', name: 'Auth0', type: 'OIDC', logo: 'auth0', issuerPattern: 'https://{your-tenant}.auth0.com', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'keycloak', name: 'Keycloak', type: 'OIDC', logo: 'keycloak', issuerPattern: 'https://{host}/realms/{realm}', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'onelogin', name: 'OneLogin', type: 'OIDC', logo: 'onelogin', issuerPattern: 'https://{subdomain}.onelogin.com/oidc/2', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'ping', name: 'Ping Identity', type: 'OIDC', logo: 'ping', issuerPattern: 'https://auth.pingone.com/{envId}/as', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'jumpcloud', name: 'JumpCloud', type: 'OIDC', logo: 'jumpcloud', issuerPattern: 'https://oauth.id.jumpcloud.com', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'adfs', name: 'MS AD FS', type: 'OIDC', logo: 'adfs', issuerPattern: 'https://{adfs-host}/adfs', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },
  { key: 'oidc', name: 'Generic OIDC', type: 'OIDC', logo: 'oidc', issuerPattern: '', scopes: ['openid', 'profile', 'email'], groupClaim: 'groups', group: 'social' },

  // ── DIRECTORY ──────────────────────────────────────────────────────────────
  { key: 'ldap', name: 'LDAP / AD', type: 'Directory', logo: 'ldap', issuerPattern: '', scopes: [], groupClaim: '', group: 'directory' },

  // ── PROVISIONING ───────────────────────────────────────────────────────────
  { key: 'scim', name: 'SCIM', type: 'Provisioning', logo: 'scim', issuerPattern: '', scopes: [], groupClaim: '', group: 'provisioning' },
]
