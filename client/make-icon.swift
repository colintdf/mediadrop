import AppKit
let directory = URL(fileURLWithPath:CommandLine.arguments[1])
try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
for size in [16,32,128,256,512] {
    for scale in [1,2] {
        let pixels = size * scale
        let image = NSImage(size:NSSize(width:pixels,height:pixels))
        image.lockFocus()
        let context = NSGraphicsContext.current!.cgContext
        context.scaleBy(x:CGFloat(pixels)/1024,y:CGFloat(pixels)/1024)
        NSColor(calibratedRed:0.07,green:0.12,blue:0.17,alpha:1).setFill()
        NSBezierPath(roundedRect:NSRect(x:16,y:16,width:992,height:992),xRadius:220,yRadius:220).fill()
        NSColor(calibratedRed:0.17,green:0.76,blue:0.68,alpha:1).setStroke()
        let ring = NSBezierPath(ovalIn:NSRect(x:188,y:188,width:648,height:648)); ring.lineWidth=54; ring.stroke()
        let middle = NSBezierPath(ovalIn:NSRect(x:408,y:408,width:208,height:208)); middle.lineWidth=34; middle.stroke()
        NSColor.white.withAlphaComponent(0.7).setStroke()
        let shine=NSBezierPath(); shine.move(to:NSPoint(x:294,y:718)); shine.line(to:NSPoint(x:367,y:645)); shine.lineWidth=26; shine.lineCapStyle = .round; shine.stroke()
        image.unlockFocus()
        let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
        let suffix=scale==2 ? "@2x" : ""
        try bitmap.representation(using:.png,properties:[:])!.write(to:directory.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}
