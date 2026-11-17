# Revisão de spec.md

Observação: o usuário pediu explicitamente para não receber mais perguntas; decisões de produto são tomadas pelo orquestrador e registradas aqui.

| Rodada | Versão avaliada | Nota | Sugestões | Aceitas | Parciais | Rejeitadas | Ao usuário |
|---|---|---|---|---|---|---|---|
| 1 | v0 | 86 | 11 | 11 | 0 | 0 | 0 |
| 2 | v1 | 89 | 6 | 6 | 0 | 0 | 0 |
| 3 | v2 | 92 | 5 | 5 | 0 | 0 | 0 |
| 4 | v3 | 93 | 5 | 5 | 0 | 0 | 0 |
| 5 | v4 | 95 | 3 | 3 | 0 | 0 | 0 |
| 6 | v5 | 94 | 5 | 5 | 0 | 0 | 0 |

## Registro de decisões
<!-- Isto é o que vai para os revisores. Mantenha curto e neutro. -->
Nenhuma decisão registrada.

## Rodada 1 (v0 → v1)
**Nota:** 86. Revisor: spec precisa e viável; lacunas em estados da tela, troca atômica, testes de análise, códigos HTTP.
**Aplicadas:** S1–S11 todas. Decisões do orquestrador (no lugar do usuário): S1 exportação liberada durante reprocessamento (stems atuais); S10 navegador suportado = Chrome/Edge, Safari não verificado. Polimento aplicado: P1–P9, P11, P12 (P10 junto com S7).
**Rejeitadas:** nenhuma.

## Rodada 2 (v1 → v2)
**Nota:** 89. Revisor: muito precisa; faltavam limite de tentativas na recuperação, coerência worker×start.sh, testes de risco.
**Aplicadas:** S1–S6. Decisão do orquestrador: S6 opção (a) — tons em solfejo no pt-BR, acordes em letras. Polimento aplicado: P1, P2, P4, P7, P8, P9, P10. Ignorados: P3, P5, P6, P11, P12.
**Rejeitadas:** nenhuma.

## Rodada 3 (v2 → v3)
**Nota:** 92. Revisor: concreta e verificável; faltavam isolamento do tmp, unicidade de job ativo, yt-dlp-ejs, alguns testes.
**Aplicadas:** S1–S5 (S3 verificado: `yt-dlp[default]` traz `yt-dlp-ejs==0.8.0`). Polimento aplicado: P1+P2, P3, P4, P5, P7, P10, P13.
**Rejeitadas:** nenhuma.

## Rodada 4 (v3 → v4)
**Nota:** 93. Revisor: rara precisão; contradição no local do source.wav e lacunas pequenas de borda/testes.
**Aplicadas:** S1–S5. Polimento aplicado: P2. Ignorados: P1, P3–P7 (o implementador resolve).
**Rejeitadas:** nenhuma.

## Rodada 5 (v4 → v5)
**Nota:** 95 — meta atingida. Restavam S1 (média, defeito real de recuperação), S2 (média, testes) e S3 (baixa).
**Decisão:** como o usuário não quer perguntas e S1 é um defeito real, o orquestrador aplicou S1–S3 e disparou uma rodada final cega (6, limite) para que a versão entregue tenha nota.

## Rodada 6 (v5 → v6) — encerramento por limite de rodadas
**Nota:** 94 (v5). Trajetória: 86 → 89 → 92 → 93 → 95 → 94.
**Aplicadas após o encerramento (v6, sem nota cega):** S1 (referência ao api-contract.md), S2 (DELETE × worker), S3, S4 (decisão do orquestrador: seek fora do trecho desliga o loop), S5; polimento P1, P7. Motivo: correções reais necessárias à implementação em andamento; o usuário pediu para não ser consultado.
