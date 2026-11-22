import { getSignupEnabled } from "@/lib/auth/config";

import { SignupForm } from "./SignupForm";

// Same as the login page: the platform's signup setting is read on the server,
// so a locked-down install never shows a form whose submission would be refused.
export const dynamic = "force-dynamic";

export default async function SignupPage() {
  const signupEnabled = await getSignupEnabled();
  return <SignupForm signupEnabled={signupEnabled} />;
}
