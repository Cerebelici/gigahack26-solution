import { useMemo } from "react";
import { FieldMap } from "./FieldMap";
import { sampleResult } from "./fixture";
import { buildFieldData } from "./project";
import { SampleBanner } from "./SidePanels";

/** Public demo on fixture data; never mixed with a signed-in user's project. */
export function MapPage() {
  const data = useMemo(() => buildFieldData(sampleResult), []);
  return <FieldMap data={data} overlay={<SampleBanner />} planRoute />;
}
