import { FeatureRows } from "@/components/feature-rows";
import { Hero } from "@/components/hero";
import { OssBand } from "@/components/oss-band";
import { PositioningStatement } from "@/components/positioning-statement";
import { WaitlistSection } from "@/components/waitlist-section";

export default function LandingPage() {
  return (
    <main>
      <Hero />
      <PositioningStatement />
      <FeatureRows />
      <OssBand />
      <WaitlistSection />
    </main>
  );
}
