# Проверка этапов 1–2

## Команды на устройствах

| Где | Команда | Что должно быть |
|---|---|---|
| SW-* | `show vlan brief` | порты в нужных VLAN |
| SW-* | `show interfaces trunk` | транки up, native 999, нужные allowed VLAN |
| R1 | `show ip interface brief` | G0/0/0 и все подынтерфейсы up/up |
| R1 | `show ip dhcp binding` | 3 адреса PC1–PC3 из 192.168.10.100+ |
| R1 | `show access-lists` | (этап 2) счётчики совпадений растут |
| SW-USERS | `show port-security interface fa0/1` | Secure-up, 1 sticky MAC |

## Матрица ping

Этап 1 (без ACL): **всё ✅**. Этап 2 (после `configs/R1_ACL.txt`):

| Откуда ↓ / куда → | шлюз своего VLAN | DISPATCHER .20.20 | DATA .20.10 | FPGA1 .30.11 | GRID .40.10 | PC1 |
|---|---|---|---|---|---|---|
| PC1 | ✅ | ✅ | ❌ | ❌ | ❌ | — |
| DISPATCHER | ✅ | — | ✅ (тот же VLAN) | ✅ | ❌ | ❌ |
| DATA | ✅ | ✅ (тот же VLAN) | — | ❌ | ❌ | ❌ |
| FPGA1 | ✅ | ❌ | ❌ | ✅ (тот же VLAN) | ✅ | ❌ |
| GRID | ✅ | ❌ | ❌ | ❌ | — | ❌ |
| ADMIN | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

Проверки по TCP-портам (5000/5100/5200) — на этапе 3, когда появятся скрипты на SBC.

Дополнительно: SSH с ADMIN на R1 (`ssh -l admin 192.168.99.1`) — работает; с PC1 — нет.
