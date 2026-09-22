const smooth = (t: number) => t * t * (3 - 2 * t);
export function glassMaterial(value: number) {
  const intensity = Math.round(Math.min(100, Math.max(0, Number.isFinite(value) ? value : 50)));
  const t = intensity / 100;
  const frost = smooth(t);
  return {
    intensity, alpha: .08 + .32 * frost, blur: 1.5 + 30.5 * Math.pow(t, 1.6),
    brightness: 1 - .13 * frost, contrast: 1 + .04 * (1 - frost),
    saturation: 1 - .12 * frost, highlight: .15 + .08 * frost,
    refraction: 13 - 9 * smooth(Math.min(1, t * 1.15)),
  };
}

// Signed distance / normal of a rounded box: constant centre, bending rim.
// RG encodes a displacement vector. No random noise or image duplication.
export function lensVector(x: number, y: number, width: number, height: number, radius: number) {
  const px = x - width / 2, py = y - height / 2;
  const qx = Math.abs(px) - (width / 2 - radius), qy = Math.abs(py) - (height / 2 - radius);
  const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
  const len = Math.hypot(ox, oy);
  const distance = len + Math.min(Math.max(qx, qy), 0) - radius;
  const band = Math.max(6, Math.min(22, height / 2));
  const depth = Math.max(0, -distance);
  const weight = distance > 0 ? 0 : Math.pow(Math.max(0, 1 - depth / band), 2);
  const nx = len > 0 ? ox / len : qx > qy ? 1 : 0;
  const ny = len > 0 ? oy / len : qx > qy ? 0 : 1;
  return [Math.sign(px) * nx * weight, Math.sign(py) * ny * weight];
}

export type GlassRenderer = "svg" | "frost" | "simple";
export function rendererMode(lowGpu: boolean, svg: boolean, blur: boolean): GlassRenderer {
  return lowGpu || !blur ? "simple" : svg ? "svg" : "frost";
}

export class AuroraGlassMaterial {
  private surfaces = new Map<HTMLElement, { filter: SVGElement; image: SVGElement; displacement: SVGElement }>();
  private defs: SVGElement;
  private observer: ResizeObserver;
  private motion = matchMedia("(prefers-reduced-motion: reduce)");
  private profile = glassMaterial(50);
  private lowGpu = false;
  private svgAvailable = CSS.supports("backdrop-filter", 'url("#aurora-glass-probe")');
  private blurAvailable = CSS.supports("backdrop-filter", "blur(1px)");
  private serial = 0;
  constructor() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("aria-hidden", "true"); svg.classList.add("glass-definitions");
    this.defs = document.createElementNS(svg.namespaceURI, "defs") as SVGElement;
    svg.append(this.defs); document.body.prepend(svg);
    this.observer = new ResizeObserver(entries => {
      for (const entry of entries) this.updateMap(entry.target as HTMLElement);
    });
    this.motion.addEventListener("change", () => this.apply());
  }
  attach(element: HTMLElement) {
    if (this.surfaces.has(element)) return;
    const ns = "http://www.w3.org/2000/svg";
    const filter = document.createElementNS(ns, "filter");
    const id = `aurora-lens-${++this.serial}`;
    for (const [k, v] of Object.entries({ id, x: "0", y: "0", width: "1", height: "1", "color-interpolation-filters": "sRGB" })) filter.setAttribute(k, v);
    const image = document.createElementNS(ns, "feImage");
    image.setAttribute("result", "lens"); image.setAttribute("preserveAspectRatio", "none");
    image.setAttribute("width", "100%"); image.setAttribute("height", "100%");
    image.addEventListener("error", () => this.fallback());
    const displacement = document.createElementNS(ns, "feDisplacementMap");
    for (const [k, v] of Object.entries({ in: "SourceGraphic", in2: "lens", scale: String(this.profile.refraction), xChannelSelector: "R", yChannelSelector: "G" })) displacement.setAttribute(k, v);
    filter.append(image, displacement); this.defs.append(filter);
    this.surfaces.set(element, { filter, image, displacement });
    element.classList.add("glass-surface");
    element.style.setProperty("--glass-lens", `url("#${id}")`);
    element.addEventListener("pointermove", event => {
      if (this.lowGpu || this.motion.matches) return;
      const r = element.getBoundingClientRect();
      element.style.setProperty("--light-x", `${((event.clientX - r.left) / r.width) * 100}%`);
      element.style.setProperty("--light-y", `${((event.clientY - r.top) / r.height) * 100}%`);
    });
    element.addEventListener("pointerleave", () => {
      element.style.removeProperty("--light-x"); element.style.removeProperty("--light-y");
    });
    this.observer.observe(element); this.updateMap(element); this.apply();
  }
  set(intensity: number, lowGpu: boolean) {
    const wasLow = this.lowGpu;
    this.profile = glassMaterial(intensity); this.lowGpu = lowGpu;
    this.apply();
    if (wasLow && !lowGpu) for (const element of this.surfaces.keys()) this.updateMap(element);
  }
  // Recover without removing the surface or its interactive foreground.
  fallback() { this.svgAvailable = false; this.apply(); }
  private apply() {
    const mode = rendererMode(this.lowGpu, this.svgAvailable, this.blurAvailable);
    document.body.dataset.glassRenderer = mode;
    document.body.classList.toggle("reduced-effects", this.lowGpu);
    document.body.classList.toggle("reduced-motion", this.motion.matches);
    for (const [key, value] of Object.entries(this.profile)) {
      document.documentElement.style.setProperty(`--glass-${key}`, `${value}${key === "blur" ? "px" : ""}`);
    }
    for (const { displacement } of this.surfaces.values()) displacement.setAttribute("scale", String(mode === "svg" ? this.profile.refraction : 0));
  }
  private updateMap(element: HTMLElement) {
    if (this.lowGpu || !this.svgAvailable) return;
    const r = element.getBoundingClientRect();
    if (!r.width || !r.height) return;
    try {
      const canvas = document.createElement("canvas");
      const ratio = Math.min(1, 1024 / r.width, 512 / r.height);
      canvas.width = Math.max(1, Math.round(r.width * ratio)); canvas.height = Math.max(1, Math.round(r.height * ratio));
      const ctx = canvas.getContext("2d"); if (!ctx) { this.fallback(); return; }
      const pixels = ctx.createImageData(canvas.width, canvas.height);
      const radius = parseFloat(getComputedStyle(element).borderTopLeftRadius) || 18;
      for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
        const [nx, ny] = lensVector(x / ratio, y / ratio, r.width, r.height, radius);
        const i = (y * canvas.width + x) * 4;
        pixels.data[i] = Math.round(128 + nx * 110); pixels.data[i + 1] = Math.round(128 + ny * 110);
        pixels.data[i + 2] = 128; pixels.data[i + 3] = 255;
      }
      ctx.putImageData(pixels, 0, 0);
      this.surfaces.get(element)?.image.setAttribute("href", canvas.toDataURL());
    } catch { this.fallback(); }
  }
}
