---
name: Something doesn't work
about: Report a problem with Pi-NOMAD
title: ""
labels: bug
---

**What happened?**


**What did you expect to happen?**


**Steps to make it happen again**
1.
2.

**Your setup**
- Raspberry Pi model and memory (for example Pi 5, 4 GB):
- Storage (SD card or SSD, and size):
- Raspberry Pi OS version (`cat /etc/os-release`):
- On the hotspot or your home network?

**Logs (if an app won't start)**
Run this on the Pi and paste the result, after removing anything private:

```
cd /opt/pi-nomad && sudo docker compose logs --tail 50
```
