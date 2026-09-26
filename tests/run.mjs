import { createServer } from "vite";

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  appType: "custom",
  logLevel: "error",
});

try {
  await server.ssrLoadModule("/tests/tiffAnnotations.test.ts");
  console.log("tiff annotation tests passed");
  await server.ssrLoadModule("/tests/routeTargets.test.ts");
  console.log("route target tests passed");
} finally {
  await server.close();
}
