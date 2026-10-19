/** Keep sign-in destinations on known customer screens; never accept arbitrary redirect URLs. */
export function customerDestination(value: string | null): string {
  return value && ["/c/requests", "/c/status", "/c/profile", "/c/documents"].includes(value) ? value : "/c/requests";
}
