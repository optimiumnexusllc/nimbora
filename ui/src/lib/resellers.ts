import type { Company } from "@/client/types.gen";

/** Back from a suspension: its trial if it still runs, else active. */
export const resumedStatus = (company: Company): "trialing" | "active" =>
    company.trial_ends_at && new Date(company.trial_ends_at) > new Date() ? "trialing" : "active";
