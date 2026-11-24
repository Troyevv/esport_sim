// Disposable URL recipient for the Windows Server Core container, which has no browser.
using System;
using System.IO;
using System.Text;

public static class BrowserProbe {
    public static int Main(string[] args) {
        foreach (var argument in args) {
            Uri url;
            if (Uri.TryCreate(argument, UriKind.Absolute, out url) &&
                url.Scheme == "http" && url.Host == "127.0.0.1" && url.AbsolutePath == "/") {
                var path = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "opened.txt");
                File.AppendAllText(path, url.AbsoluteUri + Environment.NewLine, Encoding.UTF8);
                return 0;
            }
        }
        return 1;
    }
}
