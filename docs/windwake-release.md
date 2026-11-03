# Releases Android do fork Windwake

A branch `windwake/android-poco-profile` integra a base de desenvolvimento e mantém o launcher e os fluxos upstream. As correções de toque inicial, redesenho dos controles, saves transacionais e identificação do dispositivo interno do Poco estão nas fontes atuais.

O workflow manual **Windwake Android release candidate** gera somente Android ARM64. Ele não publica releases e não recebe chaves privadas. Os builds gerais upstream continuam disponíveis; seus eventos automáticos de release e cache noturno ficam restritos ao repositório upstream. Isso evita procurar uma branch `devel` inexistente neste fork e iniciar compilações sem publicação útil.

## Gerar o candidato

```powershell
gh workflow run windwake-release.yml --repo GenissonEmilio/Windwake --ref windwake/android-poco-profile -f version_name=0.3.0 -f version_code=4 -f native_version=v0.5.0-windwake.0.3.0
```

`version_code` deve crescer a cada APK distribuído, inclusive em relação a builds locais instalados. A versão Android é independente da versão nativa: o prefixo nativo `v0.5.0` preserva a comparação de compatibilidade do catálogo de mods.

O workflow:

- Valida as versões e executa os testes de reaproveitamento do compilador.
- Compila o runtime e o extrator das fontes do commit atual, com NDK fixado; gera um SDK novo e empacota as fontes atuais do setup Python.
- Reaproveita somente os três executáveis LLVM e seus dados/licenças do APK oficial v0.5.0. O APK portador, cada executável, os dados, a identidade LLVM/NDK e as fontes dos scripts de compilação/empacotamento têm checksums fixados. Mudanças nesses scripts exigem revisar essa decisão.
- Não reaproveita o SDK, Python ou extrator antigos e não aplica o antigo patch de um objeto binário.
- Gera `dev.windwake.android`, nome Windwake, sem Quest Theater. Os parâmetros opcionais de identidade não alteram os padrões upstream do Gradle.
- Confere identidade, versão, ABI, assinatura, SDK embutido, extrator e compilador; executa o guard de conteúdo distribuído.
- Publica um artifact com APK, `SHA256SUMS.txt` e `provenance.json`, incluindo commit, run e identidades dos componentes.

O APK contém runtime, setup e ferramentas. Não contém `libmain.so`, jogo, chaves ou fixtures de teste. O código específico do jogo continua sendo preparado no aparelho a partir do dump do jogador.

## Assinar e distribuir

A assinatura do artifact é temporária e serve à verificação do CI. Antes de distribuir, assine localmente com a mesma chave da release Windwake instalada, confira a assinatura com `apksigner verify --print-certs` e recalcule o checksum. Não publique keystores ou senhas nem substitua a assinatura por uma chave diferente.

Preserve os dados de procedência do CI e registre separadamente o checksum e o certificado do APK distribuído após essa assinatura. O candidato deve corresponder ao commit divulgado; um APK de um commit anterior não substitui o build atual.

Uma atualização com a mesma identidade e assinatura mantém os dados do aplicativo. O setup pode recompilar o jogo quando a identidade do SDK muda. Não é necessário desinstalar o aplicativo para esse processo.

## Verificações locais

```powershell
python tools/android/test_save_startup.py
python tools/android/test_reuse_release_compiler.py
```

Para conferir os parâmetros opcionais sem gerar um APK incompleto:

```powershell
cd android
.\gradlew.bat :app:processReleaseMainManifest '-PwwhdQuestTheater=false' '-PwwhdApplicationId=dev.windwake.android' '-PwwhdAppLabel=Windwake' '-PwwhdVersionName=0.3.0' '-PwwhdVersionCode=4' --no-daemon
```

Esse último comando valida o manifesto; não produz um setup distribuível. Para obter um APK completo, use o workflow que empacota todos os componentes.
