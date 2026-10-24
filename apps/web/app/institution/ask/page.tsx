import { redirect } from "next/navigation";

/** Ask Weza is contextual assistance on the Command Centre, not a separate workspace. */
export default function AskRedirect() {
  redirect("/institution");
}
