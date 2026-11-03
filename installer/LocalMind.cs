using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class LocalMind {
    [STAThread] static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "core", "pythonw.exe");
        if (!File.Exists(python)) {
            MessageBox.Show("Среда LocalMind отсутствует. Запустите установщик для восстановления.", "LocalMind");
            return;
        }
        try {
            var info = new ProcessStartInfo(python, "-m localmind.desktop");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            using (var process = Process.Start(info)) {
                process.WaitForExit();
                if (process.ExitCode != 0) {
                    MessageBox.Show("LocalMind не удалось запустить. Повторите установку для восстановления компонентов. Модели и настройки сохранятся.", "LocalMind");
                }
            }
        } catch (Exception) {
            MessageBox.Show("Не удалось запустить LocalMind. Восстановите установку.", "LocalMind");
        }
    }
}
