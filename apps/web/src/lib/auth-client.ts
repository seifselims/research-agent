// Browser-side Better Auth client: signIn, signUp, signOut, useSession, and token() for the API.
import { jwtClient } from "better-auth/client/plugins";
import { createAuthClient } from "better-auth/react";

export const authClient = createAuthClient({
  plugins: [jwtClient()],
});
