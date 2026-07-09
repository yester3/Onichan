# main.py - Versión mejorada con persistencia y envío a canal

import discord
from discord.ext import commands, tasks
import asyncio
import random
import string
import aiohttp
import os
import json
from datetime import datetime

# Configuración
TOKEN = os.getenv('DISCORD_TOKEN')
CHECK_INTERVAL = 0.5  # segundos entre verificaciones

# Archivos de persistencia
CHECKED_NAMES_FILE = "checked_names.json"
CONFIG_FILE = "config.json"

# Cargar nombres ya verificados
def load_checked_names():
    if os.path.exists(CHECKED_NAMES_FILE):
        with open(CHECKED_NAMES_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get("unavailable", [])), set(data.get("errors", [])), set(data.get("available", []))
    return set(), set(), set()

# Guardar nombres verificados
def save_checked_names(unavailable, errors, available):
    with open(CHECKED_NAMES_FILE, 'w') as f:
        json.dump({
            "unavailable": list(unavailable),
            "errors": list(errors),
            "available": list(available)
        }, f)

# Cargar configuración
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

# Guardar configuración
def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

# Cargar datos al inicio
checked_unavailable, checked_errors, checked_available = load_checked_names()
all_checked = checked_unavailable.union(checked_errors).union(checked_available)
config = load_config()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=",", intents=intents)

def generate_username():
    """Genera un nombre aleatorio de 3, 4 o 5 caracteres que no haya sido verificado antes"""
    max_attempts = 1000
    
    for _ in range(max_attempts):
        length = random.choice([3, 4, 5])
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
        
        if username not in all_checked:
            return username
    
    return None  # Si no encuentra ninguno nuevo después de 1000 intentos

async def check_username(username):
    """Verifica si un nombre de usuario está disponible en Discord"""
    url = f"https://discord.com/api/v9/users/{username}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Authorization": f"Bot {TOKEN}"
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 404:
                    return "available"
                elif response.status == 200:
                    return "unavailable"
                elif response.status == 429:
                    return "rate_limited"
                else:
                    return "error"
        except Exception as e:
            print(f"Error al verificar {username}: {e}")
            return "error"

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    print(f'Nombres verificados previamente: {len(all_checked)}')
    print(f'Nombres disponibles encontrados: {len(checked_available)}')
    
    # Iniciar el loop de verificación si hay un canal configurado
    if config.get("channel_id"):
        check_usernames.start()
        print(f"Verificación automática activada en canal ID: {config['channel_id']}")

@bot.command()
async def set(ctx, channel: discord.TextChannel = None):
    """Configura el canal donde se enviarán los nombres disponibles"""
    if channel is None:
        await ctx.send("❌ Debes mencionar un canal. Ejemplo: `,set #nombres-disponibles`")
        return
    
    config["channel_id"] = channel.id
    save_config(config)
    
    # Reiniciar el task si ya estaba corriendo
    if check_usernames.is_running():
        check_usernames.restart()
    else:
        check_usernames.start()
    
    await ctx.send(f"✅ Canal configurado: {channel.mention}\nLos nombres disponibles se enviarán aquí automáticamente.")

@bot.command()
async def stop(ctx):
    """Detiene la verificación automática"""
    if check_usernames.is_running():
        check_usernames.cancel()
        await ctx.send("⏹️ Verificación automática detenida.")
    else:
        await ctx.send("ℹ️ La verificación ya está detenida.")

@bot.command()
async def start(ctx):
    """Inicia la verificación automática"""
    if not config.get("channel_id"):
        await ctx.send("❌ Primero configura un canal con `,set #canal`")
        return
    
    if check_usernames.is_running():
        await ctx.send("ℹ️ La verificación ya está activa.")
    else:
        check_usernames.start()
        channel = bot.get_channel(config["channel_id"])
        await ctx.send(f"▶️ Verificación automática iniciada en {channel.mention if channel else 'el canal configurado'}.")

@bot.command()
async def stats(ctx):
    """Muestra estadísticas de nombres verificados"""
    embed = discord.Embed(title="📊 Estadísticas", color=discord.Color.blue())
    embed.add_field(name="Total verificados", value=len(all_checked), inline=True)
    embed.add_field(name="No disponibles", value=len(checked_unavailable), inline=True)
    embed.add_field(name="Disponibles encontrados", value=len(checked_available), inline=True)
    embed.add_field(name="Con error", value=len(checked_errors), inline=True)
    
    if checked_available:
        recent = list(checked_available)[-5:]
        embed.add_field(name="Últimos disponibles", value=", ".join(recent), inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def reset(ctx, confirm: str = None):
    """Limpia la lista de nombres verificados (usar con precaución)"""
    if confirm != "confirmar":
        await ctx.send("⚠️ Esto borrará TODO el historial de nombres verificados.\n"
                      "Si estás seguro, escribe: `,reset confirmar`")
        return
    
    global checked_unavailable, checked_errors, checked_available, all_checked
    
    checked_unavailable.clear()
    checked_errors.clear()
    checked_available.clear()
    all_checked.clear()
    
    save_checked_names(checked_unavailable, checked_errors, checked_available)
    await ctx.send("🗑️ Historial de nombres verificados eliminado.")

@bot.command()
async def checkone(ctx, *, username: str = None):
    """Verifica un nombre específico manualmente"""
    if not username:
        await ctx.send("❌ Debes proporcionar un nombre. Ejemplo: `,checkone abc`")
        return
    
    username = username.lower().strip()
    
    if username in all_checked:
        if username in checked_available:
            await ctx.send(f"✅ `{username}` ya fue verificado y está **DISPONIBLE**")
        elif username in checked_unavailable:
            await ctx.send(f"❌ `{username}` ya fue verificado y está **NO DISPONIBLE**")
        else:
            await ctx.send(f"⚠️ `{username}` ya fue verificado y dio **ERROR**")
        return
    
    msg = await ctx.send(f"🔍 Verificando `{username}`...")
    
    result = await check_username(username)
    
    if result == "available":
        checked_available.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        
        embed = discord.Embed(
            title="✅ Nombre Disponible",
            description=f"**`{username}`**",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.set_footer(text="Revisa disponibilidad en Discord")
        await ctx.send(embed=embed)
        await msg.edit(content=f"✅ `{username}` está disponible")
        
    elif result == "unavailable":
        checked_unavailable.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        await msg.edit(content=f"❌ `{username}` no está disponible")
        
    elif result == "rate_limited":
        await msg.edit(content=f"⏳ Rate limit alcanzado. Espera un momento...")
        
    else:
        checked_errors.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        await msg.edit(content=f"⚠️ Error al verificar `{username}`. Se guardó para no repetir.")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_usernames():
    """Loop principal de verificación automática"""
    if not config.get("channel_id"):
        return
    
    channel = bot.get_channel(config["channel_id"])
    if not channel:
        print(f"Error: No se encontró el canal {config['channel_id']}")
        return
    
    # Generar nombre no verificado previamente
    username = generate_username()
    
    if username is None:
        print("⚠️ Se agotaron las combinaciones posibles o se alcanzó el límite de intentos")
        await channel.send("⚠️ Advertencia: Se están agotando las combinaciones de nombres disponibles.")
        check_usernames.cancel()
        return
    
    result = await check_username(username)
    
    if result == "available":
        # Guardar en disponibles
        checked_available.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        
        # Enviar embed al canal
        embed = discord.Embed(
            title="✅ Nombre Disponible Encontrado",
            description=f"**`{username}`**",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Longitud", value=f"{len(username)} caracteres", inline=True)
        embed.add_field(name="Total encontrados", value=len(checked_available), inline=True)
        embed.set_footer(text="Haz clic para copiar el nombre")
        
        await channel.send(embed=embed)
        print(f"✅ Nombre disponible encontrado: {username}")
        
    elif result == "unavailable":
        # Guardar como no disponible
        checked_unavailable.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        print(f"❌ No disponible: {username}")
        
    elif result == "rate_limited":
        print("⏳ Rate limit alcanzado, esperando...")
        await asyncio.sleep(5)
        
    else:
        # Guardar como error para no repetir
        checked_errors.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        print(f"⚠️ Error con: {username} (guardado en blacklist)")

@check_usernames.before_loop
async def before_check():
    await bot.wait_until_ready()

# Comando de ayuda actualizado
@bot.command()
async def help(ctx):
    """Muestra la ayuda del bot"""
    embed = discord.Embed(
        title="🤖 Comandos Disponibles",
        description="Bot de verificación de nombres de usuario (3-5 caracteres)",
        color=discord.Color.blue()
    )
    
    embed.add_field(name=",set #canal", value="Configura el canal para enviar nombres disponibles", inline=False)
    embed.add_field(name=",start", value="Inicia la verificación automática", inline=False)
    embed.add_field(name=",stop", value="Detiene la verificación automática", inline=False)
    embed.add_field(name=",stats", value="Muestra estadísticas de nombres verificados", inline=False)
    embed.add_field(name=",checkone <nombre>", value="Verifica un nombre específico manualmente", inline=False)
    embed.add_field(name=",reset confirmar", value="Limpia el historial de nombres (⚠️ peligroso)", inline=False)
    embed.add_field(name=",help", value="Muestra este mensaje", inline=False)
    
    await ctx.send(embed=embed)

# Sobrescribir el comando help original
bot.remove_command('help')

bot.run(TOKEN)
