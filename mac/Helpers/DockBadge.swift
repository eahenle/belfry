// Experimental read-only Dock Accessibility observer.
// Does not read messages, session tokens, or browser state.
import AppKit
import ApplicationServices
import Foundation

func emit(_ state: String, count: Int? = nil) {
    var obj: [String: Any] = ["state": state]
    if let count { obj["count"] = count }
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8) ?? "{}")
}

func stringAttribute(_ element: AXUIElement, _ name: String) -> String? {
    var raw: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &raw) == .success else { return nil }
    return raw as? String
}

func childElements(_ element: AXUIElement) -> [AXUIElement] {
    var raw: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &raw) == .success else { return [] }
    return raw as? [AXUIElement] ?? []
}

func numeral(_ text: String) -> Int? {
    // Status labels vary by macOS version/localization. No invented zero.
    let regex = try! NSRegularExpression(pattern: #"(?<!\d)\d{1,7}(?!\d)"#)
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    guard let match = regex.firstMatch(in: text, range: range),
          let r = Range(match.range, in: text) else { return nil }
    return Int(text[r])
}

let args = CommandLine.arguments
if args.count != 2 || args[1].isEmpty { emit("bad_arguments"); exit(64) }
if !AXIsProcessTrusted() { emit("permission_required"); exit(0) }
let name = args[1]
guard let dock = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.dock").first else {
    emit("not_found"); exit(0)
}

let root = AXUIElementCreateApplication(dock.processIdentifier)
var queue: [(AXUIElement, Int)] = [(root, 0)]
var seen = 0
var matched = false
while !queue.isEmpty && seen < 1200 {
    let (element, depth) = queue.removeFirst()
    seen += 1
    let title = stringAttribute(element, kAXTitleAttribute as String)
        ?? stringAttribute(element, kAXDescriptionAttribute as String)
    if let title, title == name || title.hasPrefix(name + ",") {
        matched = true
        if let badge = stringAttribute(element, "AXStatusLabel") ?? stringAttribute(element, "AXBadgeValue") {
            if let count = numeral(badge) { emit("numeric_badge", count: count); exit(0) }
            emit("nonnumeric_badge"); exit(0)
        }
        // Some macOS releases put the status label on the parent, others on the icon.
        for child in childElements(element) {
            if let badge = stringAttribute(child, "AXStatusLabel"), let count = numeral(badge) {
                emit("numeric_badge", count: count); exit(0)
            }
        }
        emit("no_badge"); exit(0)
    }
    if depth < 8 {
        queue.append(contentsOf: childElements(element).map { ($0, depth + 1) })
    }
}
emit(matched ? "no_badge" : "not_found")
