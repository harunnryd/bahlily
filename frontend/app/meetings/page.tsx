import { Suspense } from "react";

import { MeetingDetailSkeleton, MeetingPage } from "@/components/meeting-page";

export default function MeetingDetailRoute() {
  return (
    <Suspense fallback={<MeetingDetailSkeleton />}>
      <MeetingPage />
    </Suspense>
  );
}
