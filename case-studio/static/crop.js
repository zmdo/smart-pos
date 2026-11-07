/* Fixed-aspect independent crop windows. Pointer movement never reshapes a person. */
export async function openCrop(photos, onSave, previewUrl = null) {
  const host = document.querySelector("#modal");
  let closed = false;
  host.innerHTML = `<div class="modal-backdrop"><section class="crop-dialog" role="dialog" aria-modal="true" aria-labelledby="crop-title"><div class="section-title"><div><span class="eyebrow">COVER FRAMING</span><h2 id="crop-title">调整封面照片取景</h2><p>拖动框调整位置，拖动右下角改变范围。固定 500:478，等比缩放。</p></div><button id="crop-close" aria-label="关闭">×</button></div><p id="crop-loading" class="muted" role="status">正在载入原图，加载完成后可调整取景…</p><div class="crop-editors">${photos.map((_, i) => `<div><h3>${i ? "训练后" : "训练前"}</h3><canvas id="crop-${i}" aria-label="${i ? "训练后" : "训练前"}取景框"></canvas><div class="crop-controls"><label>取景大小 <input type="range" min="20" max="100" id="crop-zoom-${i}"></label><button id="crop-reset-${i}">重置</button></div><div class="crop-nudges" data-index="${i}"><button data-dx="-1">←</button><button data-dy="-1">↑</button><button data-dy="1">↓</button><button data-dx="1">→</button></div></div>`).join("")}</div><div class="live-pair"><span>实时取景预览</span><canvas id="crop-pair" width="1000" height="478"></canvas></div><p class="muted">棋盘格表示原图没有像素的区域，请将取景框放在完整照片内。应用后点击「更新展示效果」刷新完整封面。</p><p id="crop-error" class="error-text"></p><div class="modal-actions"><button id="crop-cancel">取消</button><button class="primary" id="crop-save" disabled>应用取景 ↗</button></div></section></div>`;
  document.body.classList.add("modal-open");
  const data = [];
  const ratio = 500 / 478;
  const close = () => {
    closed = true;
    host.innerHTML = "";
    document.body.classList.remove("modal-open");
    window.removeEventListener("keydown", key);
  };
  const key = (e) => {
    if (e.key === "Escape") close();
  };
  window.addEventListener("keydown", key);
  for (const s of ["#crop-close", "#crop-cancel"])
    document.querySelector(s).onclick = close;
  async function decodeImage(im) {
    try {
      await im.decode();
    } catch {
      if (!closed)
        document.querySelector("#crop-loading").textContent =
          "原图加载失败，请关闭后重新打开取景器。";
      throw new Error("原图加载失败，请重试");
    }
  }
  let baseCover = null;
  if (previewUrl) {
    baseCover = new Image();
    baseCover.src = previewUrl;
    await decodeImage(baseCover);
    if (closed) return;
    const live = document.querySelector("#crop-pair");
    live.width = 1080;
    live.height = 1440;
    live.classList.add("full-cover");
    document.querySelector(".live-pair span").textContent = "实时成品预览";
  }
  for (let i = 0; i < photos.length; i++) {
    const p = photos[i],
      im = new Image();
    im.src = p.url;
    await decodeImage(im);
    if (closed) return;
    const canvas = document.querySelector("#crop-" + i),
      scale = Math.min(520 / im.width, 490 / im.height);
    canvas.width = Math.round(im.width * scale);
    canvas.height = Math.round(im.height * scale);
    const rect = p.crop.map((v, j) => v * (j % 2 ? im.height : im.width));
    data.push({ p, im, canvas, rect, scale, initial: [...rect] });
    let drag;
    const point = (e) => {
      const box = canvas.getBoundingClientRect();
      return [
        ((e.clientX - box.left) / box.width) * im.width,
        ((e.clientY - box.top) / box.height) * im.height,
      ];
    };
    canvas.onpointerdown = (e) => {
      const [x, y] = point(e),
        [rx, ry, rw, rh] = data[i].rect;
      drag = {
        x,
        y,
        rect: [...data[i].rect],
        resize: Math.hypot(x - rx - rw, y - ry - rh) < 45 / scale,
      };
      canvas.setPointerCapture(e.pointerId);
    };
    canvas.onpointermove = (e) => {
      if (!drag) return;
      const [x, y] = point(e),
        r = [...drag.rect];
      if (drag.resize) {
        r[2] = Math.max(
          im.width * 0.08,
          Math.min(
            im.width - r[0],
            (im.height - r[1]) * ratio,
            drag.rect[2] + x - drag.x,
          ),
        );
        r[3] = r[2] / ratio;
      } else {
        r[0] = Math.max(0, Math.min(im.width - r[2], r[0] + x - drag.x));
        r[1] = Math.max(0, Math.min(im.height - r[3], r[1] + y - drag.y));
      }
      data[i].rect = r;
      draw();
    };
    canvas.onpointerup = canvas.onpointercancel = () => (drag = null);
    const slider = document.querySelector("#crop-zoom-" + i);
    slider.oninput = () => {
      let r = data[i].rect;
      const max = Math.min(im.width, im.height * ratio),
        w = (max * Number(slider.value)) / 100,
        h = w / ratio;
      r = [
        Math.max(0, Math.min(im.width - w, r[0] + (r[2] - w) / 2)),
        Math.max(0, Math.min(im.height - h, r[1] + (r[3] - h) / 2)),
        w,
        h,
      ];
      data[i].rect = r;
      draw();
    };
    document.querySelector("#crop-reset-" + i).onclick = () => {
      data[i].rect = [...data[i].initial];
      draw();
    };
    document.querySelectorAll(`[data-index="${i}"] button`).forEach(
      (b) =>
        (b.onclick = () => {
          const r = data[i].rect;
          r[0] = Math.max(
            0,
            Math.min(
              im.width - r[2],
              r[0] + Number(b.dataset.dx || 0) * im.width * 0.005,
            ),
          );
          r[1] = Math.max(
            0,
            Math.min(
              im.height - r[3],
              r[1] + Number(b.dataset.dy || 0) * im.height * 0.005,
            ),
          );
          draw();
        }),
    );
  }
  function draw() {
    const pair = document.querySelector("#crop-pair").getContext("2d");
    pair.fillStyle = "#f3f0ea";
    pair.fillRect(0, 0, 1000, 478);
    if (baseCover) {
      pair.drawImage(baseCover, 0, 0, 1080, 1440);
      pair.save();
      pair.beginPath();
      pair.moveTo(84, 460);
      pair.lineTo(996, 460);
      pair.quadraticCurveTo(1040, 460, 1040, 504);
      pair.lineTo(1040, 938);
      pair.lineTo(40, 938);
      pair.lineTo(40, 504);
      pair.quadraticCurveTo(40, 460, 84, 460);
      pair.closePath();
      pair.clip();
      pair.fillRect(40, 460, 1000, 478);
    }
    data.forEach(({ im, canvas, rect, scale }, i) => {
      const c = canvas.getContext("2d");
      c.clearRect(0, 0, canvas.width, canvas.height);
      c.drawImage(im, 0, 0, canvas.width, canvas.height);
      c.fillStyle = "#10151899";
      c.fillRect(0, 0, canvas.width, canvas.height);
      const [x, y, w, h] = rect;
      c.drawImage(im, x, y, w, h, x * scale, y * scale, w * scale, h * scale);
      c.strokeStyle = "#e70012";
      c.lineWidth = 3;
      c.strokeRect(x * scale, y * scale, w * scale, h * scale);
      c.fillStyle = "white";
      c.fillRect((x + w) * scale - 7, (y + h) * scale - 7, 14, 14);
      c.strokeStyle = "#ffffff66";
      c.lineWidth = 1;
      for (let k = 1; k < 3; k++) {
        c.beginPath();
        c.moveTo((x + (w * k) / 3) * scale, y * scale);
        c.lineTo((x + (w * k) / 3) * scale, (y + h) * scale);
        c.moveTo(x * scale, (y + (h * k) / 3) * scale);
        c.lineTo((x + w) * scale, (y + (h * k) / 3) * scale);
        c.stroke();
      }
      pair.drawImage(
        im,
        x,
        y,
        w,
        h,
        i * 500 + (baseCover ? 40 : 0),
        baseCover ? 460 : 0,
        500,
        478,
      );
      document.querySelector("#crop-zoom-" + i).value =
        (w / Math.min(im.width, im.height * ratio)) * 100;
    });
    if (baseCover) pair.restore();
  }
  draw();
  document.querySelector("#crop-loading").hidden = true;
  document.querySelector("#crop-save").disabled = false;
  document.querySelector("#crop-save").onclick = async () => {
    const b = document.querySelector("#crop-save");
    b.disabled = true;
    try {
      const crops = Object.fromEntries(
        data.map(({ p, im, rect }) => [
          p.asset_id,
          rect.map((v, j) => v / (j % 2 ? im.height : im.width)),
        ]),
      );
      await onSave(crops);
      close();
    } catch (e) {
      document.querySelector("#crop-error").textContent = e.message;
      b.disabled = false;
    }
  };
}
