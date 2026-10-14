# Sincronia

Programa gratuito que sincroniza automaticamente os vídeos de várias câmeras
com o áudio de um gravador externo, comparando o som, como o antigo PluralEyes.
O resultado é exportado como uma sequência para o **Adobe Premiere Pro**.

Funciona no **Mac** (Apple Silicon e Intel) e no **Windows**.

## Como usar

1. Organize os arquivos em pastas, uma para cada câmera ou gravador. Exemplo:
   ```
   Filmagem/
     Camera A/   A001.mp4  A002.mp4 ...
     Camera B/   C0001.mp4 ...
     Gravador/   ZOOM0001.wav ...
   ```
   Cada pasta vira uma trilha no Premiere. Se os arquivos estiverem todos
   juntos, clique com o botão direito neles na lista **Mídia** e escolha
   **Definir Câmera/Gravador…**.
2. Abra o Sincronia e arraste as pastas para a janela (ou use **Adicionar Mídia…**).
3. Clique em **Sincronizar**. Clipes sincronizados ganham ✓; os que não
   encontraram par ficam em vermelho (✕); ⚠ indica um clipe longo em que os
   relógios dos aparelhos se afastaram (ele é alinhado pelo meio).
4. Clique em **Exportar para Premiere…** e salve o arquivo.
5. No Premiere: **Arquivo › Importar…**, escolha o XML e abra a sequência criada.

Na linha do tempo, use Ctrl/⌘ + rolagem (ou pinça no trackpad) para aproximar.

Não mova nem renomeie os vídeos e áudios entre a exportação e a importação no Premiere.

## Instalação

### Mac
1. Baixe o arquivo `Sincronia-…-mac-apple-silicon.zip` (Macs com chip M1, M2, M3, M4…)
   ou `Sincronia-…-mac-intel.zip` (Macs mais antigos, com processador Intel).
   Para saber qual é o seu: menu  › Sobre Este Mac › “Chip” ou “Processador”.
2. Dê dois cliques no zip e arraste o **Sincronia** para a pasta **Aplicativos**.
3. Na primeira vez, o macOS avisa que não pode verificar o desenvolvedor
   (o programa é gratuito e não tem assinatura paga da Apple). Para liberar:
   - Tente abrir o Sincronia uma vez e feche o aviso.
   - Vá em **Ajustes do Sistema › Privacidade e Segurança**, role até o fim e
     clique em **Abrir Mesmo Assim**.

   Se aparecer “o app está danificado”, abra o **Terminal** e cole:
   ```
   xattr -dr com.apple.quarantine /Applications/Sincronia.app
   ```

### Windows
1. Baixe e extraia o `Sincronia-…-windows.zip`.
2. Abra a pasta e dê dois cliques em **Sincronia.exe**.
3. Se aparecer “O Windows protegeu o computador”, clique em
   **Mais informações › Executar assim mesmo**.

## Dicas para uma boa sincronização

- Todas as câmeras precisam gravar o próprio áudio, mesmo que ruim. É ele que o programa compara.
- Clipes muito curtos (menos de ~5 s) ou só com silêncio/ruído constante podem não sincronizar.
- Clipes que não sincronizaram aparecem em vermelho e vão para o fim da sequência.

## Para desenvolvedores

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt pyinstaller pytest   # Windows: .venv\Scripts\pip
python -m pytest            # testes
python -m sincronia         # abre o programa
python -m sincronia.cli PASTA... -o saida.xml   # linha de comando
python build.py             # gera o aplicativo em dist/
```

O GitHub Actions (`.github/workflows/build.yml`) gera os aplicativos de Mac e
Windows a cada envio para a branch `main`.
