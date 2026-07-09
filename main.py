# main.py - Versión corregida con verificación real

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
CHECK_INTERVAL = 2.0  # Aumentado para ev rate limits

# Archivos de persistencia
CHECKED_NAMES_FILE = "checked_names.json"
CONFIG_FILE = "config.json"

def load_checked_names():
    if os.path.exists(CHECKED_NAMES_FILE):
        with open(CHECKED_NAMES_FILE, 'r') as f:
            data = json.load(f)
            return (
                set(data.get("unavailable", [])), 
                set(data.get("errors", [])), 
                set(data.get("available", []))
            )
    return set(), set(), set()

def save_checked_names(unavailable, errors, available):
    with open(CHECKED_NAMES_FILE, 'w') as f:
        json.dump({
            "unavailable": list(unavailable),
            "errors": list(errors),
            "available": list(available)
        }, f)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

checked_unavailable, checked_errors, checked_available = load_checked_names()
all_checked = checked_unavailable.union(checked_errors).union(checked_available)
config = load_config()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)

def generate_username():
    max_attempts = 100
    for _ in range(max_attempts):
        length = random.choice([3, 4, 5])
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
        if username not in all_checked:
            return username
    return None

async def check_username(username):
    """
    Verifica disponibilidad usando el endpoint de cambio de username.
    Esto consume el rate limit de cambio de nombre (1 vez cada 2 semanas aprox),
    por lo que solo se debe usar para nombres cortos valiosos.
    """
    url = "https://discord.com/api/v9/users/@me"
    
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    payload = {
        "username": username
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.patch(url, headers=headers, json=payload) as response:
                data = await response.json()
                
                if response.status == 200:
                    # Éxito - nombre cambiado (estaba disponible)
                    return "available"
                elif response.status == 400:
                    # Error de validación
                    error_msg = str(data).lower()
                    if "username" in error_msg and ("taken" in error_msg or "unavailable" in error_msg):
                        return "unavailable"
                    elif "rate limit" in error_msg or "too many" in error_msg:
                        return "rate_limited"
                    else:
                        print(f"Error 400: {data}")
                        return "error"
                elif response.status == 429:
                    return "rate_limited"
                else:
                    print(f"Status inesperado {response.status}: {data}")
                    return "error"
                    
        except Exception as e:
            print(f"Excepción al verificar {username}: {e}")
            return "error"

@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    print(f'Nombres verificados: {len(all_checked)}')
    print(f'Disponibles: {len(checked_available)}')
    
    if config.get("channel_id"):
        check_usernames.start()
        print(f"Verificación activada en canal: {config['channel_id']}")

@bot.command(name="set")
async def set_channel(ctx, channel: discord.TextChannel = None):
    if channel is None:
        await ctx.send("❌ Usa: `,set #canal`")
        return
    
    config["channel_id"] = channel.id
    save_config(config)
    
    if check_usernames.is_running():
        check_usernames.restart()
    else:
        check_usernames.start()
    
    await ctx.send(f"✅ Canal configurado: {channel.mention}")

@bot.command()
async def stop(ctx):
    if check_usernames.is_running():
        check_usernames.cancel()
        await ctx.send("⏹️ Verificación detenida.")
    else:
        await ctx.send("ℹ️ Ya está detenida.")

@bot.command()
async def start(ctx):
    if not config.get("channel_id"):
        await ctx.send("❌ Configura un canal primero: `,set #canal`")
        return
    
    if check_usernames.is_running():
        await ctx.send("ℹ️ Ya está activa.")
    else:
        check_usernames.start()
        await ctx.send("▶️ Verificación iniciada.")

@bot.command()
async def stats(ctx):
    embed = discord.Embed(title="📊 Estadísticas", color=discord.Color.blue())
    embed.add_field(name="Total", value=len(all_checked), inline=True)
    embed.add_field(name="No disponibles", value=len(checked_unavailable), inline=True)
    embed.add_field(name="Disponibles", value=len(checked_available), inline=True)
    embed.add_field(name="Errores", value=len(checked_errors), inline=True)
    
    if checked_available:
        recent = list(checked_available)[-5:]
        embed.add_field(name="Últimos", value=", ".join(recent), inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def reset(ctx, confirm: str = None):
    global checked_unavailable, checked_errors, checked_available, all_checked
    
    if confirm != "confirmar":
        await ctx.send("⚠️ Escribe `,reset confirmar` para borrar todo.")
        return
    
    checked_unavailable.clear()
    checked_errors.clear()
    checked_available.clear()
    all_checked.clear()
    
    save_checked_names(checked_unavailable, checked_errors, checked_available)
    await ctx.send("🗑️ Historial eliminado.")

@bot.command()
async def checkone(ctx, *, username: str = None):
    if not username:
        await ctx.send("❌ Usa: `,checkone abc`")
        return
    
    username = username.lower().strip()
    
    if username in all_checked:
        status = "✅ DISPONIBLE" if username in checked_available else "❌ NO DISPONIBLE" if username in checked_unavailable else "⚠️ ERROR"
        await ctx.send(f"`{username}` ya fue verificado: {status}")
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
        await ctx.send(embed=embed)
        await msg.edit(content=f"✅ `{username}` disponible")
        
    elif result == "unavailable":
        checked_unavailable.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        await msg.edit(content=f"❌ `{username}` no disponible")
        
    elif result == "rate_limited":
        await msg.edit(content=f"⏳ Rate limit. Espera...")
        
    else:
        checked_errors.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        await msg.edit(content=f"⚠️ Error con `{username}`. Guardado en blacklist.")

@tasks.loop(seconds=CHECK_INTERVAL)
async def check_usernames():
    if not config.get("channel_id"):
        return
    
    channel = bot.get_channel(config["channel_id"])
    if not channel:
        print(f"Canal no encontrado: {config['channel_id']}")
        return
    
    username = generate_username()
    if username is None:
        print("Sin combinaciones nuevas")
        await channel.send("⚠️ Se agotaron los nombres posibles.")
        check_usernames.cancel()
        return
    
    print(f"Verificando: {username}")
    result = await check_username(username)
    print(f"Resultado: {result}")
    
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
        embed.add_field(name="Longitud", value=f"{len(username)}", inline=True)
        embed.add_field(name="Total", value=len(checked_available), inline=True)
        
        await channel.send(embed=embed)
        print(f"✅ Disponible: {username}")
        
    elif result == "unavailable":
        checked_unavailable.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        print(f"❌ No disponible: {username}")
        
    elif result == "rate_limited":
        print("⏳ Rate limit")
        await asyncio.sleep(10)
        
    else:
        checked_errors.add(username)
        all_checked.add(username)
        save_checked_names(checked_unavailable, checked_errors, checked_available)
        print(f"⚠️ Error: {username}")

@check_usernames.before_loop
async def before_check():
    await bot.wait_until_ready()

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🤖 Comandos",
        description="Bot de nombres (3-5 caracteres)",
        color=discord.Color.blue()
    )
    embed.add_field(name=",set #canal", value="Canal para enviar nombres", inline=False)
    embed.add_field(name=",start", value="Inicia verificación", inline=False)
    embed.add_field(name=",stop", value="Detiene verificación", inline=False)
    embed.add_field(name=",stats", value="Estadísticas", inline=False)
    embed.add_field(name=",checkone <nombre>", value="Verifica manual", inline=False)
    embed.add_field(name=",reset confirmar", value="Borra historial", inline=False)
    await ctx.send(embed=embed)

bot.run(TOKEN)
