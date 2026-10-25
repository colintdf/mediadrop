import SwiftUI
import AppKit

@main
struct MediaDropRipper: App {
    @StateObject private var model = RipperModel()
    var body: some Scene {
        WindowGroup {
            RipperView(model:model).frame(minWidth:1040,minHeight:740)
                .onReceive(NotificationCenter.default.publisher(for:NSApplication.willTerminateNotification)) { _ in model.stop() }
        }
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing:.appInfo) { Button("About MediaDrop Ripper") { NSApplication.shared.orderFrontStandardAboutPanel() } }
        }
    }
}
struct RipperView: View {
    @ObservedObject var model: RipperModel
    @State private var showCompleted = false
    private let teal = Color(red:0.17,green:0.76,blue:0.68)
    var body: some View {
        HStack(spacing:0) {
            VStack(alignment:.leading,spacing:24) {
                Image(systemName:"opticaldisc.fill").font(.system(size:46)).foregroundStyle(teal)
                VStack(alignment:.leading,spacing:5) {
                    Text("MediaDrop").font(.system(size:25,weight:.bold,design:.rounded))
                    Text("CD RIPPER").font(.system(size:11,weight:.semibold)).tracking(3).foregroundStyle(.secondary)
                }
                Label("320 kbps MP3",systemImage:"waveform").font(.headline)
                Text("From your CD shelf\nto your music library.").foregroundStyle(.secondary).lineSpacing(5)
                Divider()
                Text("YOUR SERVER").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                TextField("http://Mac:12345",text:$model.server).textFieldStyle(.roundedBorder).disabled(model.busy)
                HStack { Button("Connect",action:model.connect).disabled(model.busy); Button(action:model.openServer) { Image(systemName:"arrow.up.right.square") }.help("Open MediaDrop") }
                Picker("Music folder",selection:$model.folder) {
                    Text("Choose destination").tag("")
                    ForEach(model.folders) { Text($0.name).tag($0.id) }
                }.disabled(model.busy)
                Spacer()
                Button("Show saved files",action:model.revealCache).buttonStyle(.link)
                Text("MusicBrainz metadata\nCover Art Archive images").font(.caption).foregroundStyle(.secondary)
            }.padding(28).frame(width:235).background(Color(nsColor:.controlBackgroundColor))
            ScrollView {
                VStack(alignment:.leading,spacing:22) {
                    HStack(alignment:.top) {
                        VStack(alignment:.leading,spacing:6) {
                            Text("Give your CDs a new home.").font(.system(size:28,weight:.bold,design:.rounded))
                            Text("Review the details. Rip once. Upload directly.").foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Find CD",action:model.findCD).buttonStyle(.borderedProminent).tint(teal).disabled(model.busy)
                        Button("Choose CD folder…",action:model.chooseCD).disabled(model.busy)
                    }
                    if !model.error.isEmpty { Label(model.error,systemImage:"exclamationmark.triangle.fill").foregroundStyle(.orange).textSelection(.enabled) }
                    HStack(spacing:20) {
                        ZStack {
                            RoundedRectangle(cornerRadius:16).fill(teal.opacity(0.12))
                            if let cover = model.cover { Image(nsImage:cover).resizable().scaledToFit().clipShape(RoundedRectangle(cornerRadius:16)) }
                            else { Image(systemName:"opticaldisc").font(.system(size:70,weight:.ultraLight)).foregroundStyle(teal) }
                        }.frame(width:150,height:150)
                        VStack(alignment:.leading,spacing:12) {
                            if !model.choices.isEmpty {
                                Picker("Release",selection:$model.release) {
                                    Text("Choose the matching edition").tag("")
                                    ForEach(model.choices) { Text($0.label).tag($0.id) }
                                }.onChange(of:model.release) { _ in model.applyRelease() }
                            }
                            HStack { field("Album",text:$model.album); field("Album artist",text:$model.artist) }
                            HStack { field("Year / date",text:$model.date); field("Genre",text:$model.genre); field("Disc",text:$model.discNumber).frame(width:65) }
                        }.disabled(model.busy)
                    }
                    HStack {
                        Text("TRACKS").font(.caption.weight(.bold)).tracking(2)
                        Text("\(model.tracks.filter { $0.selected }.count) selected").foregroundStyle(.secondary)
                        Spacer()
                        Button("Look up CD",action:model.lookup).disabled(model.busy || model.tracks.isEmpty)
                    }
                    if model.tracks.isEmpty {
                        VStack(spacing:12) {
                            Image(systemName:"arrow.down.circle").font(.largeTitle).foregroundStyle(teal)
                            Text("Insert an audio CD to get started").font(.headline)
                            Text("Use a built-in or USB CD drive connected to this Mac.").foregroundStyle(.secondary)
                        }.frame(maxWidth:.infinity).padding(36).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:14))
                    } else {
                        VStack(spacing:0) {
                            HStack { Text("RIP").frame(width:30); Text("#").frame(width:25); Text("TRACK TITLE").frame(maxWidth:.infinity,alignment:.leading); Text("TRACK ARTIST").frame(width:220,alignment:.leading) }.font(.caption).foregroundStyle(.secondary).padding(.bottom,10)
                            ForEach($model.tracks) { $track in
                                HStack(spacing:12) {
                                    Toggle("",isOn:$track.selected).labelsHidden().frame(width:30)
                                    Text(String(track.id)).monospacedDigit().foregroundStyle(.secondary).frame(width:25)
                                    TextField("Track title",text:$track.title).textFieldStyle(.roundedBorder)
                                    TextField("Uses album artist",text:$track.artist).textFieldStyle(.roundedBorder).frame(width:220)
                                }.padding(.vertical,6)
                            }
                        }.disabled(model.busy)
                    }
                    VStack(alignment:.leading,spacing:8) {
                        Toggle("Compare two reads of each track",isOn:$model.doubleRead).disabled(model.busy)
                        Text("This compares the files macOS reads twice. It is not AccurateRip verification or a guarantee against drive caching.").font(.caption).foregroundStyle(.secondary)
                    }
                    HStack {
                        Button("Rip & upload selected",action:model.rip).buttonStyle(.borderedProminent).tint(teal).controlSize(.large).disabled(model.busy || model.tracks.isEmpty || model.folder.isEmpty)
                        Button("Retry pending",action:model.retry).disabled(model.busy || !model.queue.contains { $0.status != "Complete" })
                        Spacer()
                        if model.busy { ProgressView().controlSize(.small); Button("Stop",action:model.stop) }
                    }
                    VStack(alignment:.leading,spacing:8) {
                        Text(model.message).font(.callout).textSelection(.enabled)
                        if model.busy { ProgressView(value:model.progress).tint(teal) }
                    }.padding(16).frame(maxWidth:.infinity,alignment:.leading).background(teal.opacity(0.08),in:RoundedRectangle(cornerRadius:12))
                    if !model.queue.isEmpty {
                        HStack { Text("UPLOAD QUEUE").font(.caption.weight(.bold)).tracking(2); Spacer(); Toggle("Show completed",isOn:$showCompleted).toggleStyle(.checkbox) }
                        ForEach(model.queue.filter { showCompleted || $0.status != "Complete" }) { item in
                            HStack(alignment:.top) {
                                Image(systemName:item.status == "Complete" ? "checkmark.circle.fill" : "music.note").foregroundStyle(teal)
                                VStack(alignment:.leading,spacing:4) {
                                    Text(item.tags["title"] ?? item.filename).fontWeight(.medium)
                                    Text("\(item.tags["artist"] ?? "") · \(item.tags["album"] ?? "")").font(.caption).foregroundStyle(.secondary)
                                    if !item.error.isEmpty { Text(item.error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                                }
                                Spacer()
                                VStack(alignment:.trailing,spacing:5) {
                                    Text(item.status).font(.caption).foregroundStyle(.secondary)
                                    if item.status != "Complete" { Button("Remove…") { model.forget(item.id) }.buttonStyle(.link).disabled(model.busy) }
                                }
                            }.padding(.vertical,6)
                        }
                    }
                }.padding(32)
            }
        }.tint(teal)
    }
    private func field(_ name:String,text:Binding<String>) -> some View {
        VStack(alignment:.leading,spacing:5) { Text(name.uppercased()).font(.system(size:10,weight:.semibold)).foregroundStyle(.secondary); TextField(name,text:text).textFieldStyle(.roundedBorder) }
    }
}
