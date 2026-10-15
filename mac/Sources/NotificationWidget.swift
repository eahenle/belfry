import AppKit
import SwiftUI
import Combine
import Darwin

// Snapshot format v1 mirrors notifydock/model.py. Credentials never reach SwiftUI.
struct DashboardSnapshot: Decodable {
    let version: Int
    let generatedAt: String?
    let channels: [ChannelReading]

    enum CodingKeys: String, CodingKey {
        case version, channels
        case generatedAt = "generated_at"
    }
}

struct ChannelReading: Decodable, Identifiable {
    let id: String
    let provider: String
    let account: String
    let scope: String
    let metric: String
    let displayName: String
    let count: Int?
    let precision: String
    let status: String
    let detail: String
    let observedAt: String?
    let checkedAt: String?
    let lastSuccessAt: String?
    let refreshSeconds: Int
    let url: String

    enum CodingKeys: String, CodingKey {
        case id, provider, account, scope, metric, count, precision, status, detail, url
        case displayName = "display_name"
        case observedAt = "observed_at"
        case checkedAt = "checked_at"
        case lastSuccessAt = "last_success_at"
        case refreshSeconds = "refresh_seconds"
    }

    func effectiveStatus(asOf now: Date) -> String {
        if status == "ok" || status == "simulated" {
            guard let raw = observedAt, let date = DateParser.parse(raw) else { return "stale" }
            if now.timeIntervalSince(date) > Double(max(300, refreshSeconds * 2)) { return "stale" }
        }
        return status
    }

    var effectiveStatus: String { effectiveStatus(asOf: Date()) }

    var metricLabel: String {
        switch metric {
        case "unread_messages": return "Unread messages"
        case "unread_threads": return "Unread threads"
        case "unread_notification_threads": return "Unread notification threads"
        case "unread_mail_items": return "Unread mail"
        case "unread_dm_messages": return "Unread DM messages"
        case "matching_jql_issues": return "Matching issues"
        case "application_badge": return "App badge"
        case "unread_notifications": return "Unread notifications"
        default: return metric.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    var countLabel: String {
        guard let count = count else { return "·" }
        switch precision {
        case "approximate": return "≈\(count)"
        case "lower_bound": return "≥\(count)"
        default: return String(count)
        }
    }

    var helpText: String {
        let updated = observedAt ?? "never"
        let text = detail.isEmpty ? "" : "\n\(detail)"
        return "\(provider.capitalized) • \(account)\nScope: \(scope)\nMetric: \(metricLabel)\nPrecision: \(precision)\nStatus: \(effectiveStatus)\nObserved: \(updated)\(text)"
    }
}

enum DateParser {
    static func parse(_ value: String) -> Date? {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: value) { return date }
        iso.formatOptions = [.withInternetDateTime]
        return iso.date(from: value)
    }
}

enum AppLocations {
    static let home: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/NotificationWidget", isDirectory: true)
    }()
    static var snapshot: URL { home.appendingPathComponent("snapshot.json") }
    static var config: URL { home.appendingPathComponent("config.json") }
    static var refresh: URL { home.appendingPathComponent("refresh.request") }
}

final class DashboardStore: ObservableObject {
    static let shared = DashboardStore()
    @Published private(set) var channels: [ChannelReading] = []
    @Published private(set) var error: String? = nil
    @Published var showAcrossSpaces: Bool {
        didSet {
            UserDefaults.standard.set(showAcrossSpaces, forKey: "showAcrossSpaces")
            PanelManager.shared.updateSpacesBehavior()
        }
    }
    private var watcher: DispatchSourceFileSystemObject?
    private var timer: Timer?

    private init() {
        showAcrossSpaces = UserDefaults.standard.object(forKey: "showAcrossSpaces") as? Bool ?? true
    }

    func start() {
        try? FileManager.default.createDirectory(at: AppLocations.home, withIntermediateDirectories: true)
        load()
        // Watch directory, not the atomically replaced file inode.
        let fd = open(AppLocations.home.path, O_EVTONLY)
        if fd >= 0 {
            let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd,
                                        eventMask: [.write, .rename, .delete], queue: .main)
            source.setEventHandler { [weak self] in self?.load() }
            source.setCancelHandler { close(fd) }
            source.resume()
            watcher = source
        }
        // Fallback catches missed directory events, sleep/wake and staleness changes.
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            self?.load()
        }
    }

    func load() {
        do {
            let data = try Data(contentsOf: AppLocations.snapshot)
            let snapshot = try JSONDecoder().decode(DashboardSnapshot.self, from: data)
            guard snapshot.version == 1 else { throw NSError(domain: "Schema", code: 1) }
            if channels.map({ $0.id + ($0.checkedAt ?? "") + $0.status + String($0.count ?? -1) }) !=
                snapshot.channels.map({ $0.id + ($0.checkedAt ?? "") + $0.status + String($0.count ?? -1) }) {
                channels = snapshot.channels
            }
            error = nil
        } catch {
            if channels.isEmpty {
                self.error = "No snapshot yet. Run setup or start the coordinator."
            }
        }
    }

    func refresh() {
        try? FileManager.default.createDirectory(at: AppLocations.home, withIntermediateDirectories: true)
        // A file-change request, not an HTTP endpoint. No user credentials involved.
        try? UUID().uuidString.write(to: AppLocations.refresh, atomically: true, encoding: .utf8)
    }

    func openConfiguration() {
        NSWorkspace.shared.open(AppLocations.config)
    }

    func openConfigurationFolder() {
        NSWorkspace.shared.activateFileViewerSelecting([AppLocations.config])
    }
}

final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class PanelManager: NSObject, NSWindowDelegate {
    static let shared = PanelManager()
    private(set) var panel: FloatingPanel?

    func show() {
        if panel == nil { makePanel() }
        panel?.orderFrontRegardless()
    }

    func hide() { panel?.orderOut(nil) }
    func toggle() { panel?.isVisible == true ? hide() : show() }

    func updateSpacesBehavior() {
        guard let panel = panel else { return }
        if DashboardStore.shared.showAcrossSpaces {
            panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        } else {
            panel.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
        }
    }

    private func makePanel() {
        let contentRect = NSRect(x: 0, y: 0, width: 324, height: 510)
        let window = FloatingPanel(contentRect: contentRect,
                    styleMask: [.borderless, .nonactivatingPanel],
                    backing: .buffered, defer: false)
        window.backgroundColor = .clear
        window.isOpaque = false
        window.hasShadow = true
        window.level = .floating
        window.hidesOnDeactivate = false
        window.isMovableByWindowBackground = true
        window.becomesKeyOnlyIfNeeded = true
        window.delegate = self
        window.contentView = NSHostingView(rootView: DashboardView().environmentObject(DashboardStore.shared))
        panel = window
        updateSpacesBehavior()

        if let frameString = UserDefaults.standard.string(forKey: "panelFrame") {
            let saved = NSRectFromString(frameString)
            if NSScreen.screens.contains(where: { $0.visibleFrame.intersects(saved) }) {
                window.setFrame(saved, display: true)
                return
            }
        }
        if let visible = NSScreen.main?.visibleFrame {
            window.setFrameOrigin(NSPoint(x: visible.maxX - 324 - 18,
                                          y: visible.maxY - 510 - 18))
        } else {
            window.center()
        }
    }

    func windowDidMove(_ notification: Notification) {
        if let frame = panel?.frame {
            UserDefaults.standard.set(NSStringFromRect(frame), forKey: "panelFrame")
        }
    }
}

struct ChannelRow: View {
    let channel: ChannelReading
    let currentTime: Date

    private var readingStatus: String { channel.effectiveStatus(asOf: currentTime) }

    private var isTrouble: Bool {
        !["ok", "simulated"].contains(readingStatus)
    }

    private var indicator: Color {
        switch readingStatus {
        case "ok": return Color(red: 0.34, green: 0.78, blue: 0.53)
        case "simulated": return Color(red: 0.55, green: 0.65, blue: 0.96)
        case "stale", "error", "auth_required": return .orange
        default: return .secondary.opacity(0.55)
        }
    }

    private var glyph: String {
        switch channel.provider {
        case "gmail", "outlook", "yahoo": return "envelope.fill"
        case "github": return "chevron.left.forwardslash.chevron.right"
        case "jira": return "checkmark.square.fill"
        case "confluence": return "doc.on.doc.fill"
        case "discord", "slack", "webex", "whatsapp": return "bubble.left.and.bubble.right.fill"
        default: return "bell.fill"
        }
    }

    var body: some View {
        Button {
            guard let link = URL(string: channel.url), link.scheme == "https" else { return }
            NSWorkspace.shared.open(link)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: glyph)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.primary.opacity(0.80))
                    .frame(width: 33, height: 33)
                    .background(Color.primary.opacity(0.065), in: RoundedRectangle(cornerRadius: 10))
                VStack(alignment: .leading, spacing: 2) {
                    Text(channel.displayName).font(.system(size: 12.5, weight: .semibold))
                        .lineLimit(1)
                    Text(channel.metricLabel)
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                VStack(alignment: .trailing, spacing: 3) {
                    Text(channel.countLabel)
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                        .monospacedDigit()
                        .foregroundStyle(isTrouble ? Color.secondary : Color.primary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                    HStack(spacing: 4) {
                        Circle().fill(indicator).frame(width: 5, height: 5)
                        Text(shortStatus)
                            .font(.system(size: 9, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(minWidth: 42, alignment: .trailing)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .contentShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 12))
        .help(channel.helpText)
    }

    private var shortStatus: String {
        switch readingStatus {
        case "ok": return channel.precision == "limited" ? "badge" : "live"
        case "simulated": return "demo"
        case "auth_required": return "sign in"
        case "unsupported": return "unsupported"
        case "unavailable": return "unavailable"
        case "disabled": return "off"
        case "stale": return "stale"
        default: return "error"
        }
    }
}

struct DashboardView: View {
    @EnvironmentObject private var store: DashboardStore
    @State private var currentTime = Date()
    private let freshnessTimer = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 9) {
                Image(systemName: "circle.hexagongrid.fill")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.indigo)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Signals")
                        .font(.system(size: 19, weight: .bold, design: .rounded))
                    Text("Your attention, at a glance")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button { store.refresh() } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 12, weight: .semibold))
                        .frame(width: 29, height: 29)
                        .background(Color.primary.opacity(0.06), in: Circle())
                }
                .buttonStyle(.plain)
                .help("Request refresh (subject to provider rate limits)")
            }
            .padding(.top, 5)

            Rectangle().fill(Color.primary.opacity(0.10)).frame(height: 1)

            if let error = store.error, store.channels.isEmpty {
                Spacer()
                VStack(spacing: 9) {
                    Image(systemName: "antenna.radiowaves.left.and.right")
                        .font(.system(size: 28))
                        .foregroundStyle(.secondary)
                    Text(error).font(.system(size: 12)).multilineTextAlignment(.center)
                    Button("Open config folder") { store.openConfigurationFolder() }
                        .font(.system(size: 11))
                }
                Spacer()
            } else {
                ScrollView(.vertical) {
                    LazyVStack(spacing: 5) {
                        ForEach(store.channels) { channel in
                            ChannelRow(channel: channel, currentTime: currentTime)
                        }
                    }
                    .padding(.vertical, 2)
                }
                .scrollIndicators(.hidden)
            }

            HStack {
                let active = store.channels.filter { $0.effectiveStatus == "ok" }.count
                let failed = store.channels.filter { ["error", "auth_required", "stale"].contains($0.effectiveStatus) }.count
                Circle().fill(active > 0 ? Color.green : Color.secondary.opacity(0.5))
                    .frame(width: 6, height: 6)
                Text("\(active) live · \(failed) need attention · \(store.channels.count) sources")
                    .lineLimit(1)
                Spacer()
                Button { store.openConfiguration() } label: {
                    Image(systemName: "slider.horizontal.3")
                }
                .buttonStyle(.plain)
                .help("Edit channels configuration")
            }
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(.secondary)
            .padding(.bottom, 4)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(width: 324, height: 510)
        .onReceive(freshnessTimer) { currentTime = $0 }
        .background {
            RoundedRectangle(cornerRadius: 19, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay {
                    RoundedRectangle(cornerRadius: 19, style: .continuous)
                        .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.9)
                }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        DashboardStore.shared.start()
        PanelManager.shared.show()
    }
}

@main
struct NotificationWidgetApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = DashboardStore.shared

    var body: some Scene {
        MenuBarExtra("Signals", systemImage: "bell.badge") {
            Button("Show Panel") { PanelManager.shared.show() }
            Button("Hide Panel") { PanelManager.shared.hide() }
            Button("Refresh Now") { store.refresh() }
            Divider()
            Toggle("Show in All Spaces", isOn: $store.showAcrossSpaces)
            Divider()
            Button("Edit Channels JSON") { store.openConfiguration() }
            Button("Open Configuration Folder") { store.openConfigurationFolder() }
            Divider()
            Button("Quit Signals") { NSApp.terminate(nil) }
        }
    }
}
