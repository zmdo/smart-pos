export const productTypes = {
  three_views: "完整三视图",
  vs: "同朝向对比图",
  single: "朝向单图",
  cover: "会员案例封面",
  report: "体测报告对比",
  training: "会员训练日常",
  testimonial: "会员感言",
  life: "会员生活照",
};

export function downloadPlan(version, selection = null) {
  const counts = {};
  for (const member of version.members)
    for (const product of member.products)
      counts[product.kind] = (counts[product.kind] || 0) + 1;
  const available = Object.keys(productTypes).filter((kind) => counts[kind]);
  const selected = available.filter(
    (kind) => selection === null || selection.includes(kind),
  );
  const byMember = Object.fromEntries(
    version.members.map((member) => [
      member.member_id,
      member.products.filter((p) => selected.includes(p.kind)).length,
    ]),
  );
  return {
    available,
    selected,
    counts,
    byMember,
    total: Object.values(byMember).reduce((a, b) => a + b, 0),
    queryTypes: selected.length === available.length ? null : selected,
  };
}

export function archiveURL(jid, vid, member, types) {
  if (types !== null && !types.length) return null;
  const query = new URLSearchParams();
  if (member) query.set("member", member);
  if (types !== null) for (const type of types) query.append("types", type);
  return `/api/jobs/${encodeURIComponent(jid)}/download/${encodeURIComponent(vid)}${query.size ? "?" + query : ""}`;
}
