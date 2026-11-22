# Лицензии и распространение

## Исходники

Собственный код и документация LocalMind опубликованы по [MIT](../LICENSE) с разрешения разработчика wiseakk. У сторонних компонентов и моделей действуют собственные условия. Для иконок есть [генератор](../scripts/generate_app_icon.py).

| Встроенный компонент | Условия |
| --- | --- |
| Marked 15.0.12 | [MIT и историческое уведомление Markdown](../static/assets/licenses/Marked.md) |
| KaTeX 0.19.1, JS и CSS | [MIT](../static/assets/licenses/KaTeX.txt) |
| Шрифты KaTeX | [OFL 1.1 с исходными уведомлениями](../static/assets/fonts/KaTeX-OFL.txt) |
| DOMPurify 3.4.17 | Вариант [Apache 2.0](../static/assets/licenses/DOMPurify-Apache-2.0.txt) из поставляемого двойного лицензирования |
| Onest, Unbounded | [OFL](../static/assets/fonts/Onest-OFL.txt), [OFL](../static/assets/fonts/Unbounded-OFL.txt) |

Python-зависимости и Ollama обычно устанавливаются отдельно. Для поставки PySide6 и Qt WebEngine нужно учесть лицензии Qt и Chromium. [Qt WebEngine](https://doc.qt.io/qtforpython-6/overviews/qtwebengine-licensing.html)

## Пакеты и модели

Локальный Arch-пакет включает 35 Python-дистрибутивов голосового runtime, включая Piper, PyTorch и библиотеки NVIDIA cuBLAS, NVRTC и cuDNN. Публикация архива требует проверки лицензий дистрибутивов, уведомлений, предоставления исходников там, где требуется, и права распространения конкретных бинарников NVIDIA. Наличие wheel в публичном индексе само по себе не подтверждает право повторно упаковать его в наш дистрибутив. Аналогичная проверка состава нужна для Windows Setup. [Piper](https://github.com/OHF-Voice/piper1-gpl) · [NVIDIA CUDA 12.9 EULA](https://docs.nvidia.com/cuda/archive/12.9.0/pdf/EULA.pdf)

Gemma, Whisper и голосовые веса Silero имеют собственные условия. Перед загрузкой сверяйте карточку конкретного ресурса. Публикация исходников не включает эти веса. [Gemma 4](https://discuss.ai.google.dev/t/gemma-4-launch-announcement/138069)
