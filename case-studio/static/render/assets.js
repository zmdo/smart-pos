/* Shared asset/font decoding; callers choose authenticated or offline URLs. */
const loadedFonts = new Map();
export class Assets {
  constructor(materials, fonts, resolve = async (u) => u) {
    this.materials = materials;
    this.fonts = fonts;
    this.resolve = resolve;
    this.images = new Map();
    this.faces = loadedFonts;
  }
  async image(key) {
    if (!key) return null;
    if (!this.images.has(key))
      this.images.set(
        key,
        (async () => {
          const im = new Image();
          im.src = await this.resolve(this.materials.assets[key]);
          await im.decode();
          return im;
        })().catch((e) => {
          this.images.delete(key);
          throw e;
        }),
      );
    return this.images.get(key);
  }
  family(id) {
    return "studio_" + id.replaceAll("-", "_");
  }
  async font(id) {
    if (!this.faces.has(id))
      this.faces.set(
        id,
        (async () => {
          const row = this.fonts.find((f) => f.id === id);
          if (!row) throw Error("字体不存在，请重新选择");
          const f = new FontFace(this.family(id), `url("${row.url}")`, {
            weight: "100 900",
          });
          await f.load();
          document.fonts.add(f);
        })().catch((e) => {
          this.faces.delete(id);
          throw e;
        }),
      );
    return this.faces.get(id);
  }
  async prepare(member) {
    const s = member.render_settings,
      ids = new Set(
        [
          s.default_font,
          ...Object.values(s.font_overrides || {}),
          ...Object.values(member.fonts || {}),
        ].filter(Boolean),
      );
    await Promise.all([...ids].map((id) => this.font(id)));
  }
}
