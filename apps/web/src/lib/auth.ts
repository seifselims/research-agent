/**
 * Better Auth server config.
 *
 * The auth tables (user, session, account, verification, jwks) live in the shared Postgres
 * database but are created and changed ONLY by Alembic (apps/api/migrations), so the API's
 * tables can reference "user".id with a real foreign key.
 * Do not run `npx @better-auth/cli migrate`. If you add a plugin or field that changes the
 * schema, add the matching SQLAlchemy model in apps/api/src/api/models.py and an Alembic migration.
 */
import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { jwt } from "better-auth/plugins";
import { Pool } from "pg";

export const auth = betterAuth({
  database: new Pool({
    connectionString: process.env.DATABASE_URL,
    // Shares Render's small connection limit with the API's own pool (5), so keep this small.
    max: 3,
  }),
  emailAndPassword: { enabled: true },
  plugins: [
    // Issues short-lived signed JWTs (GET /api/auth/token) that the FastAPI backend verifies
    // with the public keys at /api/auth/jwks, without needing to share a secret.
    jwt(),
    // Lets server actions set auth cookies. Must stay the last plugin.
    nextCookies(),
  ],
});
