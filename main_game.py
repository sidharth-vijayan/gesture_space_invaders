"""
main_game.py (fixed - stable enemy movement + float positions + dt cap)

Fixes:
- Caps dt to avoid huge jumps on slow frames
- Uses float_x for enemy positions to avoid int rounding jumps
- Clamps per-frame enemy movement to avoid massive teleports
- Draws sprites when available else a visible fallback
- Keeps webcam overlay + CV fallback intact
- Debug-friendly (prints spawn summary)

Drop the generated enemy image into assets/enemy.png after downloading.
"""
import pygame
import sys
import time
import json
import random
from pathlib import Path

# optional CV controller import
try:
    from cv_controller import CVController
    CV_AVAILABLE = True
except Exception:
    CV_AVAILABLE = False
    CVController = None

WIDTH, HEIGHT = 900, 700
FPS = 60
ASSETS_DIR = Path(__file__).parent / "assets"
HIGHSCORE_FILE = Path.home() / ".gesture_space_invaders_highscore.json"

# Safety limits
MAX_DT = 0.05             # seconds (cap per-frame dt)
MAX_MOVE_PER_FRAME = 12   # px per frame max for enemies (prevents jumps)


def load_image(name):
    path = ASSETS_DIR / name
    if path.exists():
        try:
            img = pygame.image.load(str(path)).convert_alpha()
            # if bounding rect empty -> treat as missing
            try:
                br = img.get_bounding_rect()
                if br.width == 0 or br.height == 0:
                    print(f"DEBUG: {name} empty (transparent). ignoring sprite.")
                    return None
            except Exception:
                pass
            return img
        except Exception as e:
            print("DEBUG: failed to load", name, e)
    return None


def make_fallback_surface(size, color):
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill(color)
    return surf


def load_sound(name):
    path = ASSETS_DIR / name
    if path.exists():
        try:
            return pygame.mixer.Sound(str(path))
        except Exception:
            return None
    return None


class Player:
    def __init__(self, img):
        self.img = img
        self.rect = img.get_rect(midbottom=(WIDTH // 2, HEIGHT - 30))
        self.cooldown = 0.32
        self._last_shot = 0
        self.lives = 3

    def move_to(self, x_norm):
        if x_norm is None:
            return
        target_x = int(x_norm * WIDTH)
        self.rect.centerx = max(20, min(WIDTH - 20, target_x))

    def can_shoot(self):
        return time.time() - self._last_shot >= self.cooldown

    def make_shot(self):
        self._last_shot = time.time()


class Bullet:
    def __init__(self, x, y, vel=-7, img=None):
        self.img = img
        if img is not None:
            self.rect = img.get_rect(center=(x, y))
        else:
            self.rect = pygame.Rect(x - 2, y - 6, 4, 12)
        self.vel = vel

    def update(self):
        self.rect.y += self.vel


class Enemy:
    def __init__(self, x, y, img):
        self.img = img
        if img is not None:
            self.rect = img.get_rect(topleft=(x, y))
            self.float_x = float(self.rect.x)
            self.float_y = float(self.rect.y)
        else:
            # fallback rect (size will be used for collision/draw)
            size = 44
            self.rect = pygame.Rect(x, y, size, size)
            self.float_x = float(self.rect.x)
            self.float_y = float(self.rect.y)
        self.alive = True


class Game:
    def __init__(self):
        pygame.init()
        try:
            pygame.mixer.init()
        except Exception:
            pass
        pygame.display.set_caption("Gesture Space Invaders (fixed)")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 24)

        # load assets - ship larger for visibility
        ship_img_raw = load_image("ship.png")
        if ship_img_raw is None:
            ship_img_raw = make_fallback_surface((100, 66), (50, 200, 200))
        self.ship_img = pygame.transform.scale(ship_img_raw, (100, 66))

        enemy_raw = load_image("enemy.png")
        if enemy_raw is None:
            enemy_raw = make_fallback_surface((40, 30), (200, 60, 60))
            enemy_surface = None if enemy_raw is None else enemy_raw
        else:
            enemy_surface = enemy_raw
        # keep enemy_img as the sprite (or None)
        self.enemy_img = enemy_surface

        bullet_raw = load_image("bullet.png")
        if bullet_raw is None:
            bullet_raw = make_fallback_surface((6, 12), (255, 255, 180))
        self.bullet_img = pygame.transform.scale(bullet_raw, (6, 12))

        self.explosion_sfx = load_sound("explosion.wav")

        # game state
        self.player = Player(self.ship_img)
        self.player_score = 0
        self.level = 1
        self.bullets = []
        self.enemy_bullets = []
        self.enemies = []
        self.spawn_wave(self.level)

        # CV
        self.cv = None
        self.cv_enabled = False
        if CV_AVAILABLE:
            try:
                self.cv = CVController()
                self.cv.start()
                cap = getattr(self.cv, "cap", None)
                if cap is not None and hasattr(cap, "isOpened") and cap.isOpened():
                    self.cv_enabled = True
                else:
                    self.cv_enabled = False
            except Exception:
                self.cv_enabled = False

        self.kb_x = 0.5
        self.highscore = self.load_highscore()
        self.paused = False
        self.game_over_flag = False

        # initial debug print
        alive_count = sum(1 for e in self.enemies if e.alive)
        sample_positions = [(int(e.float_x), int(e.float_y)) for e in self.enemies[:6]]
        print(f"DEBUG: spawn_wave(level={self.level}) -> spawned {alive_count} enemies; sample positions: {sample_positions}")

    def load_highscore(self):
        if HIGHSCORE_FILE.exists():
            try:
                data = json.loads(HIGHSCORE_FILE.read_text())
                return data.get("highscore", 0)
            except Exception:
                return 0
        return 0

    def save_highscore(self):
        try:
            cur = {"highscore": max(self.highscore, self.player_score)}
            HIGHSCORE_FILE.write_text(json.dumps(cur))
        except Exception:
            pass

    def spawn_wave(self, level):
        self.enemies.clear()
        rows = 3 + (level - 1) // 2
        cols = 7
        x0 = 80
        y0 = 50
        spacing_x = 70
        spacing_y = 55
        for r in range(rows):
            for c in range(cols):
                x = x0 + c * spacing_x
                y = y0 + r * spacing_y
                img = self.enemy_img
                e = Enemy(x, y, img)
                self.enemies.append(e)
        self.enemy_dir = 1
        self.enemy_speed = 45 + (level - 1) * 8  # px/sec base
        # minor random offset to avoid perfect alignment that sometimes triggers early edge checks
        for e in self.enemies:
            e.float_x += random.uniform(-1.5, 1.5)
            e.rect.x = int(e.float_x)

    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.quit()
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.quit()
                elif ev.key == pygame.K_p:
                    self.paused = not self.paused
                elif ev.key == pygame.K_r:
                    self.reset()
                elif ev.key == pygame.K_SPACE:
                    if not self.cv_enabled and self.player.can_shoot():
                        self.player.make_shot()
                        self.bullets.append(Bullet(self.player.rect.centerx, self.player.rect.top - 6, vel=-7, img=self.bullet_img))

    def reset(self):
        self.player = Player(self.ship_img)
        self.player_score = 0
        self.level = 1
        self.bullets.clear()
        self.enemy_bullets.clear()
        self.spawn_wave(self.level)
        self.game_over_flag = False
        self.paused = False

    def quit(self):
        if self.cv is not None:
            try:
                self.cv.stop()
            except Exception:
                pass
        self.save_highscore()
        pygame.quit()
        sys.exit()

    def update_enemies(self, dt):
        if not self.enemies:
            return

        # cap dt to avoid huge jumps on resume or first frame
        dt = min(dt, MAX_DT)

        # compute move in pixels (float)
        move_px = self.enemy_speed * dt * self.enemy_dir

        # clamp per-frame movement to avoid teleporting
        if abs(move_px) > MAX_MOVE_PER_FRAME:
            move_px = MAX_MOVE_PER_FRAME * (1 if move_px > 0 else -1)

        # check if any will hit edge after moving (use float positions)
        will_hit_edge = False
        for e in self.enemies:
            if not e.alive:
                continue
            new_x = e.float_x + move_px
            # check future rect edges using width
            if new_x + e.rect.width >= WIDTH - 10 or new_x <= 10:
                will_hit_edge = True
                break

        if will_hit_edge:
            # reverse direction and drop down a fixed amount
            self.enemy_dir *= -1
            for e in self.enemies:
                if e.alive:
                    e.float_y += 12
                    e.rect.y = int(e.float_y)
        else:
            # normal move
            for e in self.enemies:
                if not e.alive:
                    continue
                e.float_x += move_px
                e.rect.x = int(e.float_x)

        # occasional enemy shooting
        if random.random() < 0.012 + (self.level * 0.002):
            shooters = [e for e in self.enemies if e.alive]
            if shooters:
                s = random.choice(shooters)
                self.enemy_bullets.append(Bullet(s.rect.centerx, s.rect.bottom + 8, vel=4, img=self.bullet_img))

    def collision_checks(self):
        for b in self.bullets[:]:
            for e in self.enemies:
                if e.alive and b.rect.colliderect(e.rect):
                    e.alive = False
                    try:
                        self.bullets.remove(b)
                    except ValueError:
                        pass
                    self.player_score += 10
                    if self.explosion_sfx:
                        try:
                            self.explosion_sfx.play()
                        except Exception:
                            pass
                    break
        for b in self.enemy_bullets[:]:
            if b.rect.colliderect(self.player.rect):
                try:
                    self.enemy_bullets.remove(b)
                except ValueError:
                    pass
                self.player.lives -= 1
                if self.player.lives <= 0:
                    self.game_over()

    def game_over(self):
        self.game_over_flag = True
        if self.player_score > self.highscore:
            self.highscore = self.player_score
            self.save_highscore()
        self.paused = True

    def draw_overlay(self, surface, gesture_img, shoot_flag, confidence):
        import cv2
        if gesture_img is not None:
            try:
                small = cv2.resize(gesture_img, (200, 140))
                small_rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                surf = pygame.image.frombuffer(small_rgb.tobytes(), (small_rgb.shape[1], small_rgb.shape[0]), "RGB")
                surface.blit(surf, (WIDTH - 210, 10))
                txt = self.font.render(f"Shoot: {'YES' if shoot_flag else 'no'}  conf: {confidence:.2f}", True, (255, 255, 255))
                surface.blit(txt, (WIDTH - 210, 160))
            except Exception:
                pass

    def run(self):
        while True:
            raw_dt = self.clock.tick(FPS) / 1000.0
            # cap high dt here as well
            dt = min(raw_dt, MAX_DT)
            self.handle_events()

            if self.paused:
                self.screen.fill((6, 6, 20))
                p = self.font.render("PAUSED - press P to resume, R to restart", True, (255, 255, 255))
                self.screen.blit(p, (20, 20))
                pygame.display.flip()
                continue

            # controls
            x_norm = None
            shoot = False
            conf = 0.0
            preview = None

            if self.cv is not None and self.cv_enabled:
                try:
                    x_norm, shoot, conf, preview = self.cv.get_controls()
                except Exception:
                    x_norm, shoot, conf, preview = None, False, 0.0, None
            else:
                keys = pygame.key.get_pressed()
                if keys[pygame.K_LEFT]:
                    self.kb_x -= 0.015
                if keys[pygame.K_RIGHT]:
                    self.kb_x += 0.015
                self.kb_x = max(0.0, min(1.0, getattr(self, "kb_x", 0.5)))
                x_norm = self.kb_x

            if x_norm is not None:
                self.player.move_to(x_norm)

            if shoot and self.player.can_shoot():
                self.player.make_shot()
                self.bullets.append(Bullet(self.player.rect.centerx, self.player.rect.top - 6, vel=-7, img=self.bullet_img))

            for b in self.bullets[:]:
                b.update()
                if b.rect.bottom < 0:
                    try:
                        self.bullets.remove(b)
                    except ValueError:
                        pass
            for b in self.enemy_bullets[:]:
                b.update()
                if b.rect.top > HEIGHT:
                    try:
                        self.enemy_bullets.remove(b)
                    except ValueError:
                        pass

            self.update_enemies(dt)
            self.collision_checks()

            if all(not e.alive for e in self.enemies):
                self.level += 1
                print("DEBUG: wave cleared. advancing to level", self.level)
                self.spawn_wave(self.level)

            # draw
            self.screen.fill((6, 6, 20))

            # player
            self.screen.blit(self.player.img, self.player.rect)

            # enemies: draw sprite if present, else visible fallback circle
            for idx, e in enumerate(self.enemies):
                if not e.alive:
                    continue
                if e.img is not None:
                    try:
                        self.screen.blit(e.img, e.rect)
                    except Exception:
                        pygame.draw.rect(self.screen, (200, 60, 60), e.rect)
                else:
                    # visible fallback: circle + index label (should never vanish)
                    center = (e.rect.centerx, e.rect.centery)
                    pygame.draw.circle(self.screen, (200, 60, 60), center, 18)
                    label = self.font.render(str(idx), True, (255, 255, 255))
                    lw = label.get_width()
                    lh = label.get_height()
                    self.screen.blit(label, (center[0] - lw // 2, center[1] - lh // 2))

            # bullets
            for b in self.bullets:
                if b.img:
                    try:
                        self.screen.blit(b.img, b.rect)
                    except Exception:
                        pygame.draw.rect(self.screen, (255, 255, 255), b.rect)
                else:
                    pygame.draw.rect(self.screen, (255, 255, 255), b.rect)
            for b in self.enemy_bullets:
                if b.img:
                    try:
                        self.screen.blit(b.img, b.rect)
                    except Exception:
                        pygame.draw.rect(self.screen, (255, 120, 120), b.rect)
                else:
                    pygame.draw.rect(self.screen, (255, 120, 120), b.rect)

            hud = self.font.render(f"Score: {self.player_score}  Lives: {self.player.lives}  Level: {self.level}  Highscore: {self.highscore}", True, (255, 255, 255))
            self.screen.blit(hud, (10, 10))

            self.draw_overlay(self.screen, preview, shoot, conf)
            pygame.display.flip()


if __name__ == "__main__":
    Game().run()
