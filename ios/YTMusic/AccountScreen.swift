import SwiftUI
import WebKit

/// Sign in to YouTube Music. Primary path: an in-app web view login (desktop user-agent to
/// reduce Google's "browser not secure" block); we then read the music.youtube.com cookies
/// from the shared store. Fallback: paste a cookie string exported from a desktop browser.
struct AccountScreen: View {
    @ObservedObject var vm: PlayerViewModel
    @ObservedObject private var account = AccountStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var showWeb = false
    @State private var pasteCookie = ""

    var body: some View {
        ZStack {
            TUI.bg.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    if account.signedIn { signedInView } else { signInView }
                }
                .padding(18)
            }
        }
        .foregroundStyle(TUI.fg).font(TUI.mono()).tint(TUI.accent).preferredColorScheme(.dark)
        .sheet(isPresented: $showWeb) { webSheet }
        .onChange(of: account.signedIn) { now in if now { vm.loadHome(force: true) } }
    }

    private var header: some View {
        HStack {
            Text("account").font(TUI.mono(18, .bold)).foregroundStyle(TUI.accent)
            Spacer()
            Text("done").font(TUI.mono(14, .bold)).foregroundStyle(TUI.accent)
                .onTapGesture { dismiss() }
        }
    }

    // MARK: - Signed in

    private var signedInView: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(TUI.accent)
                Text("signed in as").foregroundStyle(TUI.dim)
                Text(account.name.isEmpty ? "your account" : account.name)
                    .foregroundStyle(TUI.fg).font(TUI.mono(15, .bold))
            }
            Text("For You + search are personalized to this account.")
                .font(TUI.mono(12)).foregroundStyle(TUI.dim)
            Text("sign out")
                .font(TUI.mono(14, .bold)).foregroundStyle(TUI.warn)
                .padding(.vertical, 8).padding(.horizontal, 14)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(TUI.warn.opacity(0.5)))
                .onTapGesture { account.signOut() }
        }
    }

    // MARK: - Signed out

    private var signInView: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Sign in to personalize For You + search and sync liked songs.")
                .font(TUI.mono(12)).foregroundStyle(TUI.dim)

            button("⌾ sign in with browser", filled: true) { showWeb = true }

            if account.working { ProgressView().tint(TUI.accent) }
            if let e = account.lastError {
                Text(e).font(TUI.mono(11)).foregroundStyle(TUI.warn)
            }

            Divider().overlay(TUI.dim.opacity(0.3))

            Text("OR PASTE COOKIES").font(TUI.mono(11, .bold)).foregroundStyle(TUI.dim)
            Text("Paste a music.youtube.com cookie string (k=v; k=v) exported from a logged-in desktop browser.")
                .font(TUI.mono(11)).foregroundStyle(TUI.dim)
            TextField("", text: $pasteCookie,
                      prompt: Text("SAPISID=…; __Secure-3PAPISID=…").foregroundColor(TUI.dim))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .font(TUI.mono(12)).padding(8).background(TUI.panel)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(TUI.dim.opacity(0.4)))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            button("use pasted cookies", filled: false) {
                account.signIn(cookie: pasteCookie)
            }
        }
    }

    private func button(_ title: String, filled: Bool, action: @escaping () -> Void) -> some View {
        Text(title)
            .font(TUI.mono(14, .bold))
            .foregroundStyle(filled ? TUI.bg : TUI.accent)
            .padding(.vertical, 10).padding(.horizontal, 16)
            .frame(maxWidth: .infinity)
            .background(filled ? TUI.accent : Color.clear)
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(TUI.accent.opacity(filled ? 0 : 0.6)))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .onTapGesture(perform: action)
    }

    // MARK: - Web login sheet

    private var webSheet: some View {
        VStack(spacing: 0) {
            HStack {
                Text("cancel").foregroundStyle(TUI.accent).onTapGesture { showWeb = false }
                Spacer()
                Text("sign in").foregroundStyle(TUI.dim).font(TUI.mono(12))
                Spacer()
                Text(account.working ? "…" : "use account")
                    .foregroundStyle(TUI.accent).onTapGesture { capture() }
            }
            .font(TUI.mono(14, .bold)).padding(12).background(TUI.panel)
            LoginWebView()
        }
        .preferredColorScheme(.dark)
    }

    /// Read the youtube/google cookies from the shared web store and verify them.
    private func capture() {
        WKWebsiteDataStore.default().httpCookieStore.getAllCookies { cookies in
            let rel = cookies.filter {
                $0.domain.contains("google") || $0.domain.contains("youtube")
            }
            let str = rel.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
            DispatchQueue.main.async {
                account.signIn(cookie: str)
                showWeb = false
            }
        }
    }
}

/// A WKWebView that logs into YouTube with a desktop user-agent, using the shared
/// (persistent) cookie store so cookies can be read back after login.
struct LoginWebView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        let url = URL(string: "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://music.youtube.com/")!
        wv.load(URLRequest(url: url))
        return wv
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
