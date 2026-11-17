import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";
import { pathToFileURL } from "node:url";

const ROOT = "C:/Users/monis/OneDrive/Documents/Employment_Outcome_Pathway_Grouping_After_Skilling";
const SKILL = "C:/Users/monis/.codex/plugins/cache/openai-primary-runtime/presentations/26.1105.12137/skills/presentations";
const STAGE = path.join(ROOT, "reports/.presentation_build/turkey");
const FINAL = path.join(ROOT, "submission/Turkey_ISKUR_CA_presentation_v2.pptx");
const NAVY = "#10243A", TEAL = "#0E7490", GOLD = "#E7A83E", PAPER = "#F5F7FA", INK = "#152536", MUTED = "#526477", WHITE = "#FFFFFF", LINE = "#D8E0E8";
const FONT = "Arial";
await fs.mkdir(STAGE, { recursive: true });
await fs.mkdir(path.dirname(FINAL), { recursive: true });
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });

function box(slide, x, y, w, h, fill, radius = false, stroke = "none") {
  return slide.shapes.add({ geometry: radius ? "roundRect" : "rect", position: { left: x, top: y, width: w, height: h },
    fill, line: { style: "solid", fill: stroke, width: stroke === "none" ? 0 : 1 } });
}
function txt(slide, text, x, y, w, h, size = 24, color = INK, bold = false) {
  const s = slide.shapes.add({ geometry: "textbox", position: { left: x, top: y, width: w, height: h },
    fill: "none", line: { style: "solid", fill: "none", width: 0 } });
  s.text = text;
  s.text.style = { fontFamily: FONT, fontSize: size, color, bold, wrap: true, verticalAlignment: "middle" };
  return s;
}
function base(title, n) {
  const s = p.slides.add(); s.background.fill = PAPER;
  box(s, 0, 0, 1280, 12, TEAL);
  txt(s, title, 64, 38, 1110, 58, 34, NAVY, true);
  txt(s, `${n}  |  TURKEY ISKUR · 2010–2013`, 64, 675, 1110, 22, 12, MUTED, false);
  return s;
}
function notes(slide, text) { slide.speakerNotes.text = text; }
function stat(slide, x, y, value, label, accent = TEAL) {
  box(slide, x, y, 250, 112, WHITE, true, LINE);
  box(slide, x, y, 8, 112, accent);
  txt(slide, value, x + 25, y + 14, 205, 44, 31, NAVY, true);
  txt(slide, label, x + 25, y + 62, 205, 36, 16, MUTED, false);
}

// 1 — title
{
  const s = p.slides.add(); s.background.fill = NAVY;
  box(s, 900, 0, 380, 720, TEAL);
  box(s, 952, 120, 240, 480, NAVY, true);
  txt(s, "EMPLOYMENT OUTCOME PATHWAYS", 76, 115, 770, 36, 16, "#85D3DF", true);
  txt(s, "After vocational\ntraining", 76, 185, 760, 180, 54, WHITE, true);
  txt(s, "A longitudinal outcome analysis of the Turkey ISKUR evaluation", 78, 390, 720, 74, 23, "#D4E0EA", false);
  txt(s, "CA project · INT396 Unsupervised Learning · Group G24", 78, 520, 700, 40, 17, WHITE, false);
  txt(s, "Historical Turkey study, 2010–2013. Not Maharashtra or India employment evidence.", 78, 590, 760, 48, 16, "#F5D28B", true);
  notes(s, "Study source: World Bank Turkey Vocational Training Program, public-use microdata. https://microdata.worldbank.org/catalog/1973");
}
// 2 — source and cohort
{
  const s = base("A randomized offer is not the same as training received", 2);
  txt(s, "5,902", 70, 130, 255, 68, 46, TEAL, true); txt(s, "applicants in the public-use file", 70, 200, 350, 52, 21, INK);
  txt(s, "1535", 70, 300, 255, 68, 46, TEAL, true); txt(s, "source variables", 70, 370, 350, 52, 21, INK);
  const stages = [
    ["Assignment", "MM_Group", "Randomized offer"],
    ["Selection", "FF_C60", "Respondent report"],
    ["Attendance", "MIS attendance / dropout", "Observed exposure"],
    ["Completion", "MIS_EC22", "Admin completion"],
    ["Certificate", "MIS_EC23", "Receipt response"],
  ];
  stages.forEach((d, i) => {
    const x = 430 + i * 160;
    box(s, x, 150, 140, 210, WHITE, true, LINE);
    txt(s, d[0], x + 8, 172, 124, 34, 16, NAVY, true);
    txt(s, d[1], x + 12, 224, 116, 58, 15, TEAL, true);
    txt(s, d[2], x + 12, 298, 116, 45, 14, MUTED, false);
  });
  txt(s, "Unknown attendance and blank treatment-arm answers stay unknown. Course completion is not certification.", 430, 414, 770, 90, 23, NAVY, true);
  txt(s, "The official World Bank variable script confirms MIS_EC23 asks whether the evaluation-course certificate was received. We cross-checked 3,016 answered records against the derived field; mismatches: 0.", 430, 518, 760, 88, 17, MUTED);
  notes(s, "Source: World Bank related materials, including questionnaires and Create Variables File: https://microdata.worldbank.org/index.php/catalog/1973/related-materials");
}
// 3 — chronology
{
  const s = base("Only verified dates establish pre- and post-training outcomes", 3);
  const x0 = 100, y = 240, xs = [150, 450, 750, 1050];
  box(s, 155, y + 35, 870, 5, LINE);
  const nodes = [
    ["Baseline", "Interview before\nactual course start", "3,385 valid pre-course"],
    ["Training", "Exact admin start\nand end dates", "Oct 2010–May 2011"],
    ["Follow-up", "Interview after\nactual course end", "5,499 valid post-course"],
    ["Aug 2013", "Social Security\nformal employment", "Administrative point"],
  ];
  nodes.forEach((d, i) => {
    const x = xs[i]; box(s, x - 17, y + 17, 38, 38, i === 1 ? GOLD : TEAL, true);
    txt(s, d[0], x - 76, y - 52, 210, 36, 22, NAVY, true);
    txt(s, d[1], x - 76, y + 80, 205, 64, 18, INK);
    txt(s, d[2], x - 76, y + 160, 210, 38, 15, MUTED, true);
  });
  box(s, 116, 535, 1050, 75, "#E7F2F5", true);
  txt(s, "Pathway cohort: 1,546 documented attendees with all three observed outcomes", 145, 550, 990, 45, 24, NAVY, true);
  txt(s, "Sequence: any work → any work → formal work. The final measure is narrower.", 145, 610, 990, 30, 16, MUTED);
  notes(s, "Dates are parsed from MIS_EC7/MIS_EC8 and interview dates in the DTA. Source and outcome definitions: https://microdata.worldbank.org/catalog/1973");
}
// 4 — pathways prevalence
{
  const s = base("Four pathway groups summarize observed attendee sequences", 4);
  const rows = [
    ["1", "No follow-up work; no August formal job", "000 + 100", 623, 40.3, "#0E7490"],
    ["2", "No follow-up work; formal job by August 2013", "001 + 101", 245, 15.8, "#398EA3"],
    ["3", "Not working at baseline; working at follow-up", "010 + 011", 590, 38.2, "#D89A32"],
    ["4", "Working at baseline and follow-up", "110 + 111", 88, 5.7, "#AE6B4D"],
  ];
  rows.forEach((r, i) => {
    const y = 140 + i * 118;
    txt(s, `PATH ${r[0]}`, 70, y, 100, 34, 17, r[5], true);
    txt(s, r[1], 190, y, 600, 36, 21, NAVY, true);
    txt(s, `Sequences ${r[2]}  ·  n=${r[3]}  ·  ${r[4]}%`, 190, y + 42, 500, 30, 16, MUTED);
    box(s, 720, y + 7, 450, 28, "#E1E7ED", true);
    box(s, 720, y + 7, 450 * r[4] / 45, 28, r[5], true);
  });
  txt(s, "Clusters describe similarity, not causal program effects or fixed natural types.", 70, 620, 1100, 32, 18, MUTED, true);
  notes(s, "Cluster assignments are average-linkage agglomerative clustering over individual Hamming distances. Counts and shares are computed from the reproducible pipeline outputs. Source: https://microdata.worldbank.org/catalog/1973");
}
// 5 — profiles
{
  const s = base("Observed trajectories differ in timing and later formal employment", 5);
  const cols = ["Pathway", "Baseline any work", "Follow-up any work", "Aug 2013 formal work", "Median age"];
  const data = [
    ["1 · No work / no formal job", "7.1%", "0%", "0%", "26"],
    ["2 · Later formal entry", "16.3%", "0%", "100%", "24"],
    ["3 · Work begins by follow-up", "0%", "100%", "63.6%", "25"],
    ["4 · Work at both surveys", "100%", "100%", "64.8%", "26.5"],
  ];
  const widths = [420, 165, 170, 210, 120], x = [60, 480, 645, 815, 1025];
  box(s, 60, 145, 1100, 54, NAVY, true);
  cols.forEach((c, j) => txt(s, c, x[j] + 8, 154, widths[j] - 12, 38, 15, WHITE, true));
  data.forEach((r, i) => {
    const yy = 212 + i * 78; box(s, 60, yy, 1100, 66, i % 2 ? WHITE : "#EAF0F5", true);
    r.forEach((v, j) => txt(s, v, x[j] + 8, yy + 12, widths[j] - 15, 42, j === 0 ? 16 : 18, INK, j === 0));
  });
  txt(s, "Administrative first-job milestones and earnings are summarized separately; public-use data do not include monthly job-spell dates.", 70, 555, 1100, 64, 19, MUTED);
  notes(s, "Profile estimates from outputs/turkey/cluster_prevalence.csv and outputs/turkey/cluster_admin_profile.csv. Definitions are in docs/TURKEY_DATA_DICTIONARY.md. The monthly Social Security histories discussed in related research are not distributed in this public-use DTA.");
}
// 6 — validation
{
  const s = base("Separation is strong; subsample stability is moderate", 6);
  stat(s, 75, 145, "0.748", "Hamming silhouette", TEAL);
  stat(s, 365, 145, "0.620", "Mean subsample ARI", GOLD);
  stat(s, 655, 145, "0.080", "ARI standard deviation", TEAL);
  stat(s, 945, 145, "100", "80% refits", GOLD);
  txt(s, "Candidate k", 90, 335, 210, 36, 18, NAVY, true);
  const vals = [[2, 0.640], [3, 0.636], [4, 0.748], [5, 0.769]];
  vals.forEach((v, i) => {
    const x = 100 + i * 250; txt(s, `k = ${v[0]}`, x, 390, 140, 28, 17, NAVY, true);
    box(s, x, 430, 180, 30, "#E1E7ED", true); box(s, x, 430, 180 * v[1] / 0.85, 30, TEAL, true);
    txt(s, v[1].toFixed(3), x, 470, 140, 28, 17, MUTED);
  });
  txt(s, "k=5 was excluded because its smallest cluster is 2.8% (<5%). The selected k=4 solution is not a perfect pattern partition; sequences are grouped into shared outcome pathways.", 90, 535, 1060, 80, 20, INK);
  txt(s, "Low-dimensional sequence space limits claims about latent structure.", 90, 620, 1060, 28, 16, MUTED, true);
  notes(s, "Candidate silhouette and deterministic subsample stability values are computed from the released Turkey DTA, not externally reported study effects. The ARI compares refitted groups after nearest-medoid assignment.");
}
// 7 — baseline & attrition
{
  const s = base("Baseline and follow-up gaps are reported, not filled in", 7);
  stat(s, 80, 140, "3,385", "valid pre-course baseline", TEAL);
  stat(s, 365, 140, "393", "worked at baseline", GOLD);
  stat(s, 650, 140, "2,992", "not working at baseline", TEAL);
  stat(s, 935, 140, "75 / 1,623", "attendees without survey follow-up", GOLD);
  txt(s, "Follow-up any-work share", 105, 335, 420, 36, 23, NAVY, true);
  txt(s, "Not working at baseline: 42.1%", 105, 390, 480, 32, 19, INK);
  txt(s, "Working at baseline: 53.1%", 105, 432, 480, 32, 19, INK);
  txt(s, "August 2013 formal-work share", 660, 335, 490, 36, 23, NAVY, true);
  txt(s, "Not working at baseline: 41.4%", 660, 390, 480, 32, 19, INK);
  txt(s, "Working at baseline: 55.2%", 660, 432, 480, 32, 19, INK);
  box(s, 100, 505, 1050, 72, "#FCEFD7", true);
  txt(s, "Extreme follow-up work-rate bounds: 41.8%–46.5% among attendees with valid baseline", 125, 520, 1000, 42, 20, NAVY, true);
  txt(s, "Descriptive comparisons only. “Not working” is not the same as unemployed; missing outcomes remain unknown.", 100, 600, 1070, 38, 17, MUTED);
  notes(s, "Baseline group shares and sensitivity bounds come from the pipeline's strict dated cohort. Extreme bounds assign unknown survey outcomes to 0 or 1 for the calculation only; no imputed outcomes are stored. World Bank evaluation context: https://documents1.worldbank.org/curated/en/954771468318313306/pdf/823060P12051400h0final0report0small.pdf");
}
// 8 — conclusion and sources
{
  const s = base("A valid CA result—with a clear boundary", 8);
  txt(s, "What this analysis supports", 75, 145, 500, 38, 25, TEAL, true);
  txt(s, "Observed employment pathway summaries among documented Turkish vocational-training attendees, with dated baselines, administrative follow-up measures, and explicit missingness sensitivity.", 75, 198, 500, 160, 22, NAVY);
  txt(s, "What it does not support", 680, 145, 500, 38, 25, "#A2543F", true);
  txt(s, "Maharashtra or Indian employment estimates; causal effects; exact month-by-month job histories absent from the public file; or outcomes for nonrespondents.", 680, 198, 500, 160, 22, NAVY);
  box(s, 75, 430, 1100, 140, NAVY, true);
  txt(s, "Submission framing", 105, 449, 280, 32, 18, "#85D3DF", true);
  txt(s, "Present as a historical Turkey ISKUR evaluation (2010–2013). Keep PLFS work separate; it is cross-sectional and does not validate Maharashtra pathways.", 105, 490, 1010, 60, 21, WHITE, true);
  txt(s, "Sources: World Bank microdata catalog (catalog 1973); evaluation report (2013); questionnaires and variable construction file.", 80, 610, 1100, 38, 15, MUTED);
  notes(s, "Sources: https://microdata.worldbank.org/catalog/1973 ; https://documents1.worldbank.org/curated/en/954771468318313306/pdf/823060P12051400h0final0report0small.pdf ; https://microdata.worldbank.org/index.php/catalog/1973/related-materials. Geography and period limitation must remain visible in the submitted presentation.");
}

for (let i = 0; i < p.slides.items.length; i++) {
  const blob = await p.export({ slide: p.slides.items[i], format: "png", scale: 1 });
  await fs.writeFile(path.join(STAGE, `slide-${String(i + 1).padStart(2, "0")}.png`), new Uint8Array(await blob.arrayBuffer()));
}
const draft = path.join(STAGE, "draft.pptx");
await (await PresentationFile.exportPptx(p)).save(draft);
const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL, "container_tools/artifact_tool_utils.mjs")).href);
const receipt = path.join(STAGE, "validation-v2.json");
await finalizePresentation({
  workspaceDir: ROOT, candidatePath: draft, finalPath: FINAL,
  pythonExecutable: "C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1105-1297-0_26.1105.1297.0_x64__3k8sg7r9htsxt/dependencies/python/python.exe",
  integrityValidatorPath: path.join(SKILL, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-bullet-geometry", "--validate-heading-fit"],
  requiredNativeTableOwnerSlides: [], requiredNativeChartOwnerSlides: [],
  fontPolicy: { basis: "design", families: [FONT] }, verifyArtifactToolImport: true, receiptPath: receipt,
});
console.log(JSON.stringify({ final: FINAL, slides: p.slides.items.length, draft, receipt, stage: STAGE }));
