import { ApiError } from "@/lib/api";
import { Banner } from "./ui";

/** Error from a user action (approve, resolve, publish…): safe message plus the correlation reference for support.
 *  Unlike ErrorState, a 403 here keeps the server's message — e.g. "Please sign in with MFA" is not "no access". */
export function ActionError({ error, className }: { error: ApiError | null; className?: string }) {
  if (!error) return null;
  return (
    <Banner tone="danger" className={className}>
      <span>{error.message}</span>
      {error.correlationId && <span className="block text-[12px] opacity-75">Reference: {error.correlationId}</span>}
    </Banner>
  );
}
