// Command-line Security.framework credential bridge. Raw secrets are never argv.
import Foundation
import Security

let arguments = CommandLine.arguments
if arguments.count != 3 || !["get", "set", "delete"].contains(arguments[1]) {
    fputs("usage: widget-keychain {get|set|delete} reference\n", stderr)
    exit(64)
}
let action = arguments[1]
let reference = arguments[2]
let service = "dev.kernstein.notification-widget.credentials"
let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: service,
    kSecAttrAccount as String: reference,
]

func die(_ code: OSStatus) -> Never {
    fputs("Keychain operation failed (OSStatus \(code)).\n", stderr)
    exit(1)
}

if action == "get" {
    var request = query
    request[kSecReturnData as String] = true
    request[kSecMatchLimit as String] = kSecMatchLimitOne
    var found: CFTypeRef?
    let status = SecItemCopyMatching(request as CFDictionary, &found)
    if status != errSecSuccess { die(status) }
    guard let data = found as? Data, let text = String(data: data, encoding: .utf8) else { exit(1) }
    print(text, terminator: "")
} else if action == "set" {
    let raw = FileHandle.standardInput.readDataToEndOfFile()
    guard !raw.isEmpty else { exit(64) }
    let updates: [String: Any] = [kSecValueData as String: raw]
    let status = SecItemUpdate(query as CFDictionary, updates as CFDictionary)
    if status == errSecItemNotFound {
        var request = query
        request[kSecValueData as String] = raw
        let inserted = SecItemAdd(request as CFDictionary, nil)
        if inserted != errSecSuccess { die(inserted) }
    } else if status != errSecSuccess {
        die(status)
    }
} else {
    let status = SecItemDelete(query as CFDictionary)
    if status != errSecSuccess { die(status) }
}
