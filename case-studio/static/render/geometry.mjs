// Pure, trusted geometry validation in Playwright's pinned Node runtime. No browser or files.
import { plans, maskGeometry } from "./canvas.js";
let input = "";
for await (const chunk of process.stdin) input += chunk;
try {
  const { member, materials, section } = JSON.parse(input);
  const groups = plans(member)
    .products.filter((p) => p.kind === section)
    .map((p) => maskGeometry(member, materials, p, { neutral: true }));
  process.stdout.write(JSON.stringify({ groups }));
} catch (e) {
  process.stderr.write(e.message);
  process.exitCode = 1;
}
