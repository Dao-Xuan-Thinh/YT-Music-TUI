import Foundation
import Security

/// Minimal generic-password Keychain wrapper for the app's two secrets: the
/// GitHub stats token and the YouTube account cookie header. Items use
/// `AfterFirstUnlock` accessibility on purpose — the background refresh task
/// (BGAppRefreshTask) must be able to read the cookie while the device is
/// locked in a pocket.
enum Keychain {
    private static let service = "com.ytmtui.YTMusic"

    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: key]
    }

    static func get(_ key: String) -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data, !data.isEmpty
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Empty value deletes the item.
    static func set(_ key: String, _ value: String) {
        guard !value.isEmpty else { delete(key); return }
        let data = Data(value.utf8)
        var update = query(key)
        update[kSecValueData as String] = data
        update[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        let status = SecItemAdd(update as CFDictionary, nil)
        if status == errSecDuplicateItem {
            SecItemUpdate(query(key) as CFDictionary,
                          [kSecValueData as String: data] as CFDictionary)
        }
    }

    static func delete(_ key: String) {
        SecItemDelete(query(key) as CFDictionary)
    }
}
