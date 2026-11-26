// Draws the Ronic Reader logo (1024×1024 PNG): a blue "R" wearing headphones on a white background,
// over the faint text lines of an open book, with a small open book next to the R (where JustTerminal
// has its cursor and DockPane its Dock). Same geometry as the Ronic family (rounded square,
// SF Pro Rounded Black, glow, glass shine at the top).
//
//   swift branding/make-logo.swift branding/out/logo-1024.png
import AppKit
import CoreText

guard CommandLine.arguments.count == 2 else {
    print("usage: swift branding/make-logo.swift output.png"); exit(1)
}
let outputPath = CommandLine.arguments[1]

func color(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

let blue: UInt32 = 0x1F6BFF       // main blue
let blueDeep: UInt32 = 0x0A3FCC   // bottom of the R
let blueSoft: UInt32 = 0x6FA2FF   // glow and details

/// Vector path of a letter (SF Pro Rounded Black, as in the other Ronic apps).
func glyphPath(_ char: String, size: CGFloat) -> CGPath {
    let font = CTFontCreateWithName("SFProRounded-Black" as CFString, size, nil)
    let fallback = NSFont.systemFont(ofSize: size, weight: .black) as CTFont
    let useFont = (CTFontCopyPostScriptName(font) as String).contains("Rounded") ? font : fallback
    var unichars = Array(char.utf16)
    var glyphs = [CGGlyph](repeating: 0, count: unichars.count)
    CTFontGetGlyphsForCharacters(useFont, &unichars, &glyphs, unichars.count)
    return CTFontCreatePathForGlyph(useFont, glyphs[0], nil)!
}

/// Deterministic pseudo-random generator: the logo comes out identical on every run.
struct LCG {
    var state: UInt64
    mutating func next() -> CGFloat {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return CGFloat(Double(state >> 33) / Double(1 << 31))
    }
}

let px = 1024
let s = CGFloat(px)
let cs = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CGContext(data: nil, width: px, height: px, bitsPerComponent: 8, bytesPerRow: 0, space: cs,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.setShouldAntialias(true)

// ---- Background: white rounded square, a touch of blue at the bottom ----
let inset = s * 0.04
let rect = CGRect(x: inset, y: inset, width: s - inset * 2, height: s - inset * 2)
let radius = rect.width * 0.225
let bg = CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.006), blur: s * 0.02, color: color(0x0A1A40, 0.18))
ctx.addPath(bg)
ctx.setFillColor(color(0xFFFFFF))
ctx.fillPath()
ctx.restoreGState()

ctx.saveGState()
ctx.addPath(bg)
ctx.clip()
let base = CGGradient(colorsSpace: cs, colors: [color(0xFFFFFF), color(0xF3F7FF), color(0xE4EDFF)] as CFArray,
                      locations: [0, 0.6, 1])!
ctx.drawLinearGradient(base, start: CGPoint(x: 0, y: s), end: CGPoint(x: 0, y: 0), options: [])

// ---- An open book behind everything: two pages of faint text lines, split by a spine ----
var rng = LCG(state: 0xB00C_2026)
let spineX = s / 2
let lineH = s * 0.016
let gap = s * 0.046
var y = rect.maxY - s * 0.13
while y > rect.minY + s * 0.08 {
    for page in 0..<2 {
        let margin = s * 0.11
        let x0 = page == 0 ? rect.minX + margin : spineX + s * 0.05
        let maxW = (page == 0 ? spineX - s * 0.05 : rect.maxX - margin) - x0
        let w = maxW * (rng.next() > 0.85 ? 0.45 + rng.next() * 0.3 : 0.86 + rng.next() * 0.14)
        let line = CGRect(x: x0, y: y, width: w, height: lineH)
        ctx.addPath(CGPath(roundedRect: line, cornerWidth: lineH / 2, cornerHeight: lineH / 2, transform: nil))
        ctx.setFillColor(color(blue, 0.075))
        ctx.fillPath()
    }
    y -= gap
}
// Spine shadow: the page curves into the middle.
let spine = CGGradient(colorsSpace: cs, colors: [color(blue, 0), color(blue, 0.09), color(blue, 0)] as CFArray,
                       locations: [0, 0.5, 1])!
ctx.drawLinearGradient(spine, start: CGPoint(x: spineX - s * 0.06, y: 0), end: CGPoint(x: spineX + s * 0.06, y: 0), options: [])

// ---- White halo in the center so the R reads cleanly over the text ----
let halo = CGGradient(colorsSpace: cs, colors: [color(0xFFFFFF, 0.95), color(0xFFFFFF, 0)] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(halo, startCenter: CGPoint(x: s / 2, y: s * 0.48), startRadius: 0,
                       endCenter: CGPoint(x: s / 2, y: s * 0.48), endRadius: s * 0.42, options: [])

// ---- The blue R ----
let glyph = glyphPath("R", size: s * 0.5)
let gb = glyph.boundingBoxOfPath
let shiftX = s * 0.055                                     // the "R + book" pair is what gets centered
var t = CGAffineTransform(translationX: s / 2 - gb.width / 2 - gb.minX - shiftX, y: (s - gb.height) / 2 - gb.minY - s * 0.045)
let letter = glyph.copy(using: &t)!
let lb = letter.boundingBoxOfPath

ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.01), blur: s * 0.05, color: color(blue, 0.45))
ctx.addPath(letter)
ctx.setFillColor(color(blue))
ctx.fillPath()
ctx.restoreGState()

ctx.saveGState()
ctx.addPath(letter)
ctx.clip()
let ink = CGGradient(colorsSpace: cs, colors: [color(0x4D8DFF), color(blue), color(blueDeep)] as CFArray,
                     locations: [0, 0.5, 1])!
ctx.drawLinearGradient(ink, start: CGPoint(x: 0, y: lb.maxY), end: CGPoint(x: 0, y: lb.minY), options: [])
ctx.restoreGState()

// ---- Headphones on the R: a band over the top and two ear cups at the sides ----
let band = CGMutablePath()
let cx = lb.midX, top = lb.maxY
let rx = lb.width * 0.72, bandY = top - lb.height * 0.30
band.move(to: CGPoint(x: cx - rx, y: bandY))
band.addCurve(to: CGPoint(x: cx + rx, y: bandY),
              control1: CGPoint(x: cx - rx, y: top + lb.height * 0.36),
              control2: CGPoint(x: cx + rx, y: top + lb.height * 0.36))
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.004), blur: s * 0.012, color: color(blueDeep, 0.35))
ctx.addPath(band)
ctx.setStrokeColor(color(blueDeep))
ctx.setLineWidth(s * 0.034)
ctx.setLineCap(.round)
ctx.strokePath()
ctx.restoreGState()

for side in [-1.0, 1.0] as [CGFloat] {
    let cupW = s * 0.085, cupH = s * 0.15
    let cup = CGRect(x: cx + side * rx - cupW / 2, y: bandY - cupH * 0.62, width: cupW, height: cupH)
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.006), blur: s * 0.018, color: color(blueDeep, 0.45))
    ctx.addPath(CGPath(roundedRect: cup, cornerWidth: cupW * 0.48, cornerHeight: cupW * 0.48, transform: nil))
    ctx.setFillColor(color(blueDeep))
    ctx.fillPath()
    ctx.restoreGState()
    // Cushion highlight.
    let pad = cup.insetBy(dx: cupW * 0.26, dy: cupH * 0.16)
    ctx.addPath(CGPath(roundedRect: pad, cornerWidth: pad.width / 2, cornerHeight: pad.width / 2, transform: nil))
    ctx.setFillColor(color(blueSoft, 0.85))
    ctx.fillPath()
}

// ---- A small open book next to the R (the Ronic "accessory") ----
let bw = s * 0.15, bh = s * 0.085
let bx = lb.maxX + s * 0.035, by = lb.minY
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.004), blur: s * 0.02, color: color(blue, 0.55))
for side in [0, 1] {
    let p = CGMutablePath()
    let x0 = bx + bw / 2, x1 = side == 0 ? bx : bx + bw
    p.move(to: CGPoint(x: x0, y: by))
    p.addQuadCurve(to: CGPoint(x: x1, y: by + bh * 0.12), control: CGPoint(x: (x0 + x1) / 2, y: by - bh * 0.08))
    p.addLine(to: CGPoint(x: x1, y: by + bh))
    p.addQuadCurve(to: CGPoint(x: x0, y: by + bh * 0.88), control: CGPoint(x: (x0 + x1) / 2, y: by + bh * 0.92))
    p.closeSubpath()
    ctx.addPath(p)
    ctx.setFillColor(color(blue))
    ctx.fillPath()
}
ctx.restoreGState()
// Spine: a white gap between the two pages.
ctx.setStrokeColor(color(0xFFFFFF, 0.95))
ctx.setLineWidth(s * 0.007)
ctx.move(to: CGPoint(x: bx + bw / 2, y: by + bh * 0.04))
ctx.addLine(to: CGPoint(x: bx + bw / 2, y: by + bh * 0.9))
ctx.strokePath()
// White lines on the little pages.
for side in [0, 1] {
    for i in 0..<2 {
        let lw = bw * 0.26, lh = bh * 0.1
        let lx = side == 0 ? bx + bw * 0.12 : bx + bw * 0.62
        let ly = by + bh * (0.58 - 0.24 * CGFloat(i))
        ctx.addPath(CGPath(roundedRect: CGRect(x: lx, y: ly, width: lw, height: lh), cornerWidth: lh / 2, cornerHeight: lh / 2, transform: nil))
        ctx.setFillColor(color(0xFFFFFF, 0.9))
        ctx.fillPath()
    }
}

// ---- Glass shine at the top (same as the Ronic family) ----
let shine = CGGradient(colorsSpace: cs, colors: [color(0xFFFFFF, 0.7), color(0xFFFFFF, 0)] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(shine, startCenter: CGPoint(x: s * 0.3, y: s * 0.98), startRadius: 0,
                       endCenter: CGPoint(x: s * 0.3, y: s * 0.98), endRadius: s * 0.55, options: [])
ctx.restoreGState()

// Thin border so the white square still reads on white backgrounds.
ctx.addPath(bg)
ctx.setStrokeColor(color(0x0A1A40, 0.10))
ctx.setLineWidth(max(1, s * 0.004))
ctx.strokePath()

let png = NSBitmapImageRep(cgImage: ctx.makeImage()!).representation(using: .png, properties: [:])!
try png.write(to: URL(fileURLWithPath: outputPath))
print("wrote \(outputPath)")
