# Quark TWRP 3.7.0: investigação do loop para recovery

## Resultado estático

O arquivo oficial twrp-3.7.0_9-0-quark.img fornecido tem SHA256 0d0fcb443c8f2dc9ead3f01d2a4f4d8e01df463e16321e3df4de0194027eb755, igual ao checksum do servidor oficial. Seu /etc/recovery.fstab NÃO declara /misc. A imagem twrp-3.3.1-mod_1-quark.img relatada funcional pelo usuário declara /misc emmc /dev/block/platform/msm_sdcc.1/by-name/misc.

Os fontes TeamWin android-9.0 consultados mostram que twrp.cpp configura set_misc_device somente se Find_Partition_By_Path("/misc") encontrar o volume emmc. TWFunc::Update_Log_File também só chama clear_bootloader_message se /misc estiver na tabela. Sem essa declaração, o caminho normal de limpeza não é alcançado. As strings do binário oficial são compatíveis com essa implementação, mas não há manifesto fixado que prove que o HEAD consultado seja o fonte exato do binário 2022.

A hipótese forte é um pedido BCB boot-recovery persistente que não é consumido/limpo, consistente com zerar misc resolver temporariamente. Ainda falta capturar BCB/log durante uma ocorrência e validar a imagem candidata no aparelho. Não afirmar que todo reinício em recovery tem essa causa: falhas do próprio recovery e outros comandos do bootloader são possibilidades separadas.

## Fork e referência funcional

Já existe lucasgsq/twrp_device_motorola_quark, fork de fgl27/twrp_device_motorola_quark. A base master 19d3d360a6693adc6d486ee1cce9e9245b8fcec2 já contém /misc corretamente. Portanto NÃO foi adicionado um falso patch dessa linha nessa base, nem alterado o master. O branch experimental acrescenta a correção reproduzível da imagem oficial e esta documentação. Não é uma recompilação completa do core TWRP nem uma prova de que o fonte master produz o binário oficial 3.7.0.

O device tree TeamWin/android_device_motorola_quark disponível publicamente usa cm-12.1 e fstab.qcom sem misc. Não confundir esse projeto com o tree TWRP específico do fgl27, nem transplantar todo o fstab funcional: há diferenças de criptografia, modem/backup e montagem que não são necessárias ao teste.

## Imagem experimental

prebuilt/twrp-3.7.0_9-0-quark-misc-fix-test.img foi reempacotada a partir da imagem oficial verificada. A única mudança em conteúdo interno é acrescentar a linha /misc ao /etc/recovery.fstab. Kernel, DTB, second stage, cmdline, demais arquivos e metadados CPIO são preservados. A compressão LZMA-alone e seus parâmetros de decodificação são mantidos; os tamanhos e o ID SHA1 do header Android legado são recalculados e verificados.

Isso habilita o mecanismo normal de BCB do TWRP. Não inclui dd, script que zera misc, mudança de bootloader, modem, ROM, partições ou política SELinux. A configuração de SELinux do recovery não foi modificada; o estado em execução ainda requer validação. O Enforcing da ROM instalada não é alterado por este trabalho.

Candidata: 13.770.752 bytes, SHA256 7adad015de232055b269e102c0cb68b66283e4c229c8ae5da443a53677171c9e. Não testada no aparelho. Não é release oficial TeamWin.

## Reprodução no computador

```bash
python3 tools/repack-misc-fix.py twrp-3.7.0_9-0-quark.img twrp-quark-misc-test.img
```

O script usa somente biblioteca padrão Python, exige o hash oficial conhecido e recusa sobrescrever um arquivo existente. Não acessa ADB, fastboot ou dispositivos de bloco. É específico para essa imagem; não serve como repacker genérico. O SHA da saída pode variar se a versão do compressor LZMA produzir bytes diferentes; as verificações de conteúdo e header continuam necessárias.

## Validação pendente

Antes de entrar no recovery candidato, preservar recovery funcional e obter backup/leitura limitada do BCB e logs do recovery, sem apagar misc. A leitura deve identificar se existem comandos pendentes de OTA/factory reset: voltar a reconhecer misc pode permitir ao recovery processá-los. Não semear comandos de wipe nem zerar a partição para reproduzir.

Após revisão dos comandos pendentes, preferir uma sessão temporária de recovery de teste pelo método fastboot boot já usado neste aparelho, antes de substituir a partição recovery. Isso ainda permite ao recovery escrever BCB durante sua operação normal; não descrever o teste como somente leitura. A execução depende de autorização explícita e não foi realizada.

Validar inicialização, leitura de /misc como emmc, saída para sistema e nova entrada/saída voluntária; registrar /tmp/recovery.log e BCB antes/depois. Comparar a área além do bootloader_message para assegurar preservação. Não escrever no restante de misc. Manter backup da imagem funcional 3.3.1-mod_1. Não apagar dados/cache para testar esta correção.

## Fontes

- https://dl.twrp.me/quark/
- https://dl.twrp.me/quark/twrp-3.7.0_9-0-quark.img.sha256
- https://github.com/TeamWin/android_bootable_recovery/blob/android-9.0/twrp.cpp
- https://github.com/TeamWin/android_bootable_recovery/blob/android-9.0/twrp-functions.cpp
- https://github.com/TeamWin/android_bootable_recovery/blob/android-9.0/bootloader_message_twrp/bootloader_message.cpp
- https://github.com/fgl27/twrp_device_motorola_quark/blob/19d3d360a6693adc6d486ee1cce9e9245b8fcec2/recovery.fstab
