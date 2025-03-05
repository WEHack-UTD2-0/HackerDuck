import nextcord as nc
from nextcord.ext import commands as nc_cmd
import nextcord.utils as nc_utils
from nextcord.ext import application_checks as nc_app_checks

import logging
import sqlite3 as sql
import os
import json

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger('nextcord')

with open('config.json') as jsonfile:
    config = json.load(jsonfile)


# config = {
#     "DB_FILE": os.getenv("DB_FILE", "database.db"),  # Default to "database.db" if not set
#     "API_TOKEN": os.getenv("API_TOKEN"),
#     "MENTOR_CHANNEL_ID": os.getenv("MENTOR_CHANNEL_ID"),
#     "HELP_CHANNEL_ID": os.getenv("HELP_CHANNEL_ID"),
#     "GUILD_ID": os.getenv("GUILD_ID"),
#     "MENTOR_ROLE_ID": os.getenv("MENTOR_ROLE_ID"),
#     "ORGANIZER_ROLE_ID": os.getenv("ORGANIZER_ROLE_ID")
# }


bot = nc_cmd.Bot()

db_connection = sql.connect(config['DB_FILE'])

@bot.event
async def on_ready():
    logging.info(f'We have logged in as {bot.user}')
    try:
        bot.tree.clear_commands(guild=None)  # Clears previous command cache
        synced = await bot.sync_commands()
        logging.info(f"Synced {len(synced)} commands globally.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")

@bot.event
async def on_application_command_error(ctx: nc.Interaction, err: Exception):

    user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name

    logging.warning(f'User {user_name} tried to execute {ctx.application_command.qualified_name} but does not have permission to do so.')
    await ctx.send("Looks like you don't have permission to run this command... nice try :smiling_imp:", ephemeral=True)

#close {{{1
@bot.slash_command(description="Close a ticket.", guild_ids=[config['GUILD_ID']])
async def close(ctx: nc.Interaction, ticket_id: int) -> None:

    with db_connection:

        user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name

        try:

            db_cursor = db_connection.cursor()

            if ctx.user.get_role(config['MENTOR_ROLE_ID']) is None:

                ticket_info_query = db_cursor.execute('SELECT closed, claimed, mentor_assigned FROM tickets WHERE id = :ticket_id AND author_id = :user_id', {'ticket_id': ticket_id, 'user_id': ctx.user.id}).fetchone()
                
                if ticket_info_query is None:

                    logging.warning(f'User {user_name} tried to close a ticket with ID {ticket_id}, but they do not have ownership over it or it does not exist.')

                    await ctx.send(f'You do not have ownership over a ticket with ID {ticket_id}. Maybe you made a typo?', ephemeral=True)

                    return

                closed, claimed, assignee = ticket_info_query
                
                if closed == 1:

                    logging.warning(f'User {user_name} tried to close a ticket with ID {ticket_id}, but it is already closed.')

                    await ctx.send('This ticket has already been closed! :star_struck:', ephemeral=True)

                    return

                if claimed == 1:

                    await ctx.send(f'Mentor {mentor_name} has claimed this ticket. Please contact them to close it.', ephemeral=True)

                    return
                
                db_cursor.execute('UPDATE tickets SET closed = 1 WHERE id = :ticket_id', {'ticket_id': ticket_id})
                
                logging.info(f'User {user_name} closed thier own ticket with ID {ticket_id}.')

                await ctx.send('Ticket closed! :saluting_face:', ephemeral=True)

                return

            ticket_info_query = db_cursor.execute('SELECT closed, mentor_assigned_id, mentor_assigned, claimed, help_thread_id FROM tickets WHERE id = :ticket_id', {'ticket_id': ticket_id}).fetchone()

            if ticket_info_query is None:

                await ctx.send(f'A ticket with the ID {ticket_id} does not exist. Please try again.', ephemeral=True)

                logging.warning(f'Mentor {user_name} tried to close non-existant ticket with ID {ticket_id}.')

                return
            
            closed, ticket_assignee_id, ticket_assignee_name, claimed, help_thread_id = ticket_info_query
            
            if ctx.user.id != ticket_assignee_id: 

                logging.warning(f'Mentor {user_name} tried to close a ticket with ID {ticket_id} owned by {ticket_assignee_name}.' )

                await ctx.send(f'Woah there! You don\'t own this ticket... {ticket_assignee_name} does. Contact them to close it.', ephemeral=True)

                return

            if closed == 1:

                    logging.warning(f'Mentor {user_name} tried to close a ticket with ID {ticket_id}, but it is already closed.')

                    await ctx.send('This ticket has already been closed! :star_struck:', ephemeral=True)

                    return

            # if the ticket has not been claimed...
            if claimed == 0:
               
                await ctx.send(f'This ticket has not been claimed. Please claim it before closing it.', ephemeral=True)

                return 
            
            mentor_channel = await ctx.guild.fetch_channel(config['MENTOR_CHANNEL_ID'])

            help_thread = mentor_channel.get_thread(help_thread_id)

            if help_thread is None:

                logging.error(f'Mentor {user_name} tried to close a ticket with ID {ticket_id}, but help thread could not be found.' )

                await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)

                return
            
            await help_thread.delete()
            logging.info(f'Deleted help thread wth ID: {help_thread_id}.')

            db_cursor.execute('UPDATE tickets SET closed = 1 WHERE id = :ticket_id', {'ticket_id': ticket_id})
            
            db_cursor.execute('UPDATE mentors SET tickets_closed = tickets_closed + 1 WHERE id = :mentor_id', {'mentor_id': ctx.user.id})

            logging.info(f'Ticket with ID {ticket_id} has been closed by mentor {user_name}.')
            await ctx.send('Ticket closed!', ephemeral=True)

        except Exception as e:

            logging.error(f'Mentor {user_name} tried to close a ticket with ID {ticket_id}, but an unexpected error occured: {e}' )

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}
        
# claim {{{1
@bot.slash_command(description="Claim a ticket.", guild_ids=[config['GUILD_ID']])
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)
@nc_app_checks.has_role(config['MENTOR_ROLE_ID'])
async def claim(ctx: nc.Interaction, ticket_id: int) -> None:
    
    with db_connection:
        
        mentor_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name

        try:
            db_cursor = db_connection.cursor()

            mentor_query = db_cursor.execute('SELECT 1 FROM mentors WHERE id = :mentor_id', {'mentor_id': ctx.user.id}).fetchone()
            
            #new mentor!
            if mentor_query is None:

                db_cursor.execute('INSERT INTO mentors (id, name, tickets_claimed, tickets_closed) VALUES (:mentor_id, :mentor_name, 0, 0)',{'mentor_id': ctx.user.id, 'mentor_name': mentor_name})

            claim_params = {'ticket_id': ticket_id, 'mentor_id': ctx.user.id, 'mentor_name': mentor_name}
            
            ticket_query = db_cursor.execute('SELECT closed, claimed, mentor_assigned, author_id, message, author_location FROM tickets WHERE id = :ticket_id', {'ticket_id': ticket_id}).fetchone()

            if ticket_query is None:

                await ctx.send(f'A ticket with the ID {ticket_id} does not exist. Please try again.', ephemeral=True)

                logging.warning(f'Mentor {mentor_name} tried to claim non-existant ticket with ID {ticket_id}.')

                return
            
            closed, claimed, prev_assignee_name, author_id, ticket_message, author_location = ticket_query

            if closed == 1:
               
                await ctx.send(f'This ticket has already been closed! :star_struck:', ephemeral=True)

                return 

            #if ticket is already claimed...
            if claimed == 1:
               
                await ctx.send(f'This ticket has already been claimed by {prev_assignee_name}. Please contact them if you would like to help out.', ephemeral=True)

                return 
            
            ticket_author = await ctx.guild.fetch_member(author_id) 

            ticket_author_name = ticket_author.nick if ticket_author.nick else ticket_author.global_name

            help_channel = await ctx.guild.fetch_channel(config['HELP_CHANNEL_ID'])

            db_cursor.execute('UPDATE tickets SET claimed = 1, mentor_assigned_id = :mentor_id, mentor_assigned = :mentor_name WHERE id = :ticket_id', claim_params)
            
            db_cursor.execute('UPDATE mentors SET tickets_claimed = tickets_claimed + 1 WHERE id = :mentor_id', {'mentor_id': ctx.user.id})

            logging.info(f'Mentor {mentor_name} has claimed ticket with ID {ticket_id}.')

            help_thread = await help_channel.create_thread(name=f'Ticket #{ticket_id}', reason=f'Ticket #{ticket_id}')

            logging.info(f'Created help thread with ID {help_thread.id} for ticket with ID {ticket_id}.')

            await help_thread.add_user(ctx.user)
            logging.info(f'Added Mentor {mentor_name} to help thread with ID {help_thread.id}.')

            await help_thread.add_user(ticket_author)
            logging.info(f'Added User {ticket_author_name} to help thread with ID {help_thread.id}.')
            
            ticket_update_params = {'help_thread_id': help_thread.id, 'ticket_id': ticket_id}

            db_cursor.execute('UPDATE tickets SET help_thread_id = :help_thread_id WHERE id = :ticket_id', ticket_update_params)

            await ctx.send(f'Ticket #{ticket_id} claimed by {mentor_name}!')
            
            await help_thread.send(f'Greetings {ticket_author.mention}! {ctx.user.mention} is on the way to {author_location} to help you resolve the issue in your ticket:\n> {ticket_message}')

        except Exception as e:

            logging.error(f'Mentor {mentor_name} tried to claim a ticket with ID {ticket_id}, but an unexpected error occured: {e}')

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)


#1}}}

#helpme {{{1
#guild id just for testing
@bot.slash_command(description="Request help from a mentor.", guild_ids=[config['GUILD_ID']])
#check that message is from a guild and user is a member of said guild. sort of a dumb check, but need for type safety later on.
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)
async def helpme(ctx: nc.Interaction, author_location: str, ticket_message: str) -> None:

    with db_connection:
       
        author_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name #use guild nickname if available, otherwise use global name

        try:
            db_cursor = db_connection.cursor()

            mentor_channel = await ctx.guild.fetch_channel(config['MENTOR_CHANNEL_ID'])

            ticket_params = { 'message': ticket_message
                            , 'author_id': ctx.user.id
                            , 'author': author_name
                            , 'author_location': author_location
                            , 'claimed': False
                            , 'closed': False
                            }

            db_cursor.execute("""
                            INSERT INTO tickets (message, author_id, author, author_location, claimed, closed)
                            VALUES (:message, :author_id, :author, :author_location, :claimed, :closed)
                              """, ticket_params)

            logging.info(f'Received ticket from user {ticket_params["author"]} with ID {ticket_params["author_id"]}.')

            ticket_embed = nc.Embed(title='New Ticket Opened! :tickets:', description='A hacker needs help. Use `/claim` to claim this ticket!')
            
            ticket_id = db_cursor.lastrowid

            ticket_embed.add_field(name='__ID__ :hash:', value=ticket_id)
            ticket_embed.add_field(name='__Author__ :pen_fountain:', value=author_name)
            ticket_embed.add_field(name='__Location__ :round_pushpin:', value=author_location)
            ticket_embed.add_field(name='__Message__ :scroll:', value=ticket_message, inline=False)

            await mentor_channel.send(embed=ticket_embed)

            await ctx.send(f'Ticket submitted with ID {ticket_id}, help will be on the way soon!', ephemeral=True)


        except Exception as e:

            logging.error(f'User {author_name} with ID {ctx.user.id} tried to create a ticket, but an unexpected error occured: {e}' )

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}

#view all of your tickets. {{{1
@bot.slash_command(description="View all of your tickets.", guild_ids=[config['GUILD_ID']])
#check that message is from a guild and user is a member of said guild. sort of a dumb check, but need for type safety later on.
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)
async def mytix(ctx: nc.Interaction) -> None:

    with db_connection:

        try:

            db_cursor = db_connection.cursor()
            
            #if user is a mentor, treat differently
            if ctx.user.get_role(config['MENTOR_ROLE_ID']) is not None:
                tickets_query = db_cursor.execute('SELECT id, closed FROM tickets WHERE mentor_assigned_id = :mentor_id', {'mentor_id': ctx.user.id}).fetchall()
                
                if tickets_query == []:

                    await ctx.send('You have not claimed any tickets! Use `/opentix` view open tickets to claim.', ephemeral=True)

                    return

                ticket_ids, closeds = zip(*tickets_query)

                closeds = map(lambda x: ':white_check_mark:' if x == 1 else ':no_entry:', closeds)
                ticket_ids = map(str, ticket_ids)

                tickets_embed = nc.Embed(title='Your Claimed Tickets :sunglasses:', description='Use `/status` with the ticket ID for more information on a given ticket.')

                tickets_embed.add_field(name='__ID__ :hash:', value='\n'.join(ticket_ids))
                tickets_embed.add_field(name='__Closed__ :tada:', value='\n'.join(closeds))

                await ctx.send(embed=tickets_embed, ephemeral=True)

            else:
                #this is an iterable
                tickets_query = db_cursor.execute('SELECT id, claimed, closed FROM tickets WHERE author_id = :author_id', {'author_id': ctx.user.id}).fetchall()
                
                if tickets_query == []:

                    await ctx.send('You have no tickets! Use `/helpme` to open one.', ephemeral=True)

                    return

                #get a tuple for each list of fields.
                ticket_ids, claimeds, closeds = zip(*tickets_query)
           
                #prep the data for embed.
                claimeds = map(lambda x: ':white_check_mark:' if x == 1 else ':no_entry:', claimeds)
                closeds = map(lambda x: ':white_check_mark:' if x == 1 else ':no_entry:', closeds)
                ticket_ids = map(str, ticket_ids)

                tickets_embed = nc.Embed(title='Your Tickets :man_dancing:', description='Use `/status` with the ticket ID for more information on a given ticket.')

                tickets_embed.add_field(name='__ID__ :hash:', value='\n'.join(ticket_ids))
                tickets_embed.add_field(name='__Claimed__ :face_with_monocle:', value='\n'.join(claimeds))
                tickets_embed.add_field(name='__Closed__ :tada:', value='\n'.join(closeds))

                await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:

            user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name #use guild nickname if available, otherwise use global name

            logging.error(f'User {user_name} tried to view all of thier tickets, but an unexpected error occured: {e}')

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}

#view specific ticket details.{{{1
@bot.slash_command(description="View the details of a specific ticket.", guild_ids=[config['GUILD_ID']])
@nc_app_checks.check(lambda ctx: isinstance(ctx.user, nc.Member) and ctx.guild)
async def status(ctx: nc.Interaction, ticket_id: int) -> None:

    with db_connection:

        db_cursor = db_connection.cursor()

        user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name #use guild nickname if available, otherwise use global name

        try:
            
            #organizer can view all tickets.
            if ctx.user.get_role(config['ORGANIZER_ROLE_ID']) is not None or ctx.user.get_role(config['MENTOR_ROLE_ID']) is not None:

                ticket_query = db_cursor.execute('SELECT claimed, closed, mentor_assigned, message, author, author_location FROM tickets WHERE id = :ticket_id', {'ticket_id': ticket_id}).fetchone()

            else:

                #mentor or author can access ticket.
                ticket_query = db_cursor.execute('SELECT claimed, closed, mentor_assigned, message, author, author_location FROM tickets WHERE author_id = :author_id AND id = :ticket_id', {'author_id': ctx.user.id, 'ticket_id': ticket_id}).fetchone()

            if ticket_query is None:

                logging.warning(f'User {user_name} tried to view a ticket with ID {ticket_id}, but database query returned nothing.')

                await ctx.send(f'You don\'t have ownership over a ticket with ID {ticket_id}. Maybe you made a typo?', ephemeral=True)

                return
            
            claimed, closed, mentor, message, author, location = ticket_query

            ticket_embed = nc.Embed(title=f'Ticket #{ticket_id} :bug:', description=f'Opened by {author} @ {location}.')
            ticket_embed.add_field(name='__Mentor__ :military_helmet:', value=('N/A' if mentor is None else mentor))
            ticket_embed.add_field(name='__Claimed__ :face_with_monocle:', value=(':white_check_mark:' if claimed == 1 else ':no_entry:'))
            ticket_embed.add_field(name='__Closed__ :tada:', value=(':white_check_mark:' if closed == 1 else ':no_entry:'))
            ticket_embed.add_field(name='__Message__ :scroll:', value=message, inline=False)
            
            await ctx.send(embed=ticket_embed, ephemeral=True)
            
        except Exception as e:

            logging.error(f'User {user_name} tried to view a ticket with ID {ticket_id}, but an unexpected error occured: {e}')

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}

#view all open tickets {{{1 
@bot.slash_command(description="View all open tickets.", guild_ids=[config['GUILD_ID']])
@nc_app_checks.check(lambda ctx: ctx.user.get_role(config['MENTOR_ROLE_ID']) is not None or ctx.user.get_role(config['ORGANIZER_ROLE_ID']) is not None)
async def opentix(ctx: nc.Interaction) -> None:

    with db_connection:

        try:

            db_cursor = db_connection.cursor()
            
            #this is an iterable
            tickets_query = db_cursor.execute('SELECT id, author_location, author, message FROM tickets WHERE claimed = 0 AND closed = 0').fetchall()
            
            if tickets_query == []:

                await ctx.send('There are no open tickets :sob:', ephemeral=True)

                return

            #get a tuple for each list of fields.
            ticket_ids, locations, authors, messages = zip(*tickets_query)
             
            #prep the data for embed.
            ticket_ids = map(str, ticket_ids)
            logistics = map((lambda x: f'{x[0]} @ *{x[1][:10] + "..." if len(x[1]) > 10 else x[1]}*'), zip(authors, locations))
            messages = map((lambda x: f'{x[:10]}...' if len(x) > 10 else x), messages)

            tickets_embed = nc.Embed(title='Open Tickets :dancer:', description='Use `/claim` to claim an open ticket. Use `/status` to see the full details of a ticket.')

            tickets_embed.add_field(name='__ID__ :hash:', value='\n'.join(ticket_ids))
            tickets_embed.add_field(name='__Logistics__ :globe_with_meridians:', value='\n'.join(logistics))
            tickets_embed.add_field(name='__Message__ :scroll:', value='\n'.join(messages))

            await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:

            user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name #use guild nickname if available, otherwise use global name

            logging.error(f'User {user_name} tried to view all open tickets, but an unexpected error occured: {e}')

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}

#view all tickets {{{1 
@bot.slash_command(description="View all tickets.", guild_ids=[config['GUILD_ID']])
@nc_app_checks.check(lambda ctx: ctx.user.get_role(config['MENTOR_ROLE_ID']) is not None or ctx.user.get_role(config['ORGANIZER_ROLE_ID']) is not None)
async def alltix(ctx: nc.Interaction) -> None:

    with db_connection:

        try:

            db_cursor = db_connection.cursor()
            
            #this is an iterable
            tickets_query = db_cursor.execute('SELECT id, claimed, closed FROM tickets').fetchall()
            
            if tickets_query == []:

                await ctx.send('There are no tickets :fearful:', ephemeral=True)

                return

            #get a tuple for each list of fields.
            ticket_ids, claimeds, closeds = zip(*tickets_query)
             
            #prep the data for embed.
            claimeds = map(lambda x: ':white_check_mark:' if x == 1 else ':no_entry:', claimeds)
            closeds = map(lambda x: ':white_check_mark:' if x == 1 else ':no_entry:', closeds)
            ticket_ids = map(str, ticket_ids)

            tickets_embed = nc.Embed(title='All Tickets :face_with_spiral_eyes:', description='Use `/status` to view information about a specific ticket if you have claimed it. Claim an open ticket with `/claim`.')

            tickets_embed.add_field(name='__ID__ :hash:', value='\n'.join(ticket_ids))
            tickets_embed.add_field(name='__Claimed__ :face_with_monocle:', value='\n'.join(claimeds))
            tickets_embed.add_field(name='__Closed__ :tada:', value='\n'.join(closeds))

            await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:

            user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name #use guild nickname if available, otherwise use global name

            logging.error(f'User {user_name} tried to view all tickets, but an unexpected error occured: {e}')

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}

#leaderboard {{{1
@bot.slash_command(description="View which mentors have closed to most tickets.", guild_ids=[config['GUILD_ID']])
async def leaderboard(ctx: nc.Interaction) -> None:
    with db_connection:

        try:

            db_cursor = db_connection.cursor()
            
            #this is an iterable
            mentors_query = db_cursor.execute('SELECT name, tickets_claimed, tickets_closed FROM mentors ORDER BY tickets_closed DESC').fetchall()
            
            if mentors_query == []:

                await ctx.send('Welp... no mentors have claimed any tickets :skull:', ephemeral=True)

                return

            #get a tuple for each list of fields.
            mentors, num_claimed, num_closed = zip(*mentors_query)
             
            #prep the data for embed.
            mentors = map(lambda x: f'**#{x[1]}**: {x[0]}', zip(mentors,range(1,len(mentors)+1)))
            num_claimed = map(str, num_claimed)
            num_closed = map(str, num_closed)

            tickets_embed = nc.Embed(title='Mentor Leaderboard :fire:', description='Whoever closes the most tickets wins!')

            tickets_embed.add_field(name='__Mentor__ :military_helmet:', value='\n'.join(mentors))
            tickets_embed.add_field(name='__# Claimed__ :face_with_monocle:', value='\n'.join(num_claimed))
            tickets_embed.add_field(name='__# Closed__ :tada:', value='\n'.join(num_closed))

            await ctx.send(embed=tickets_embed, ephemeral=True)

        except Exception as e:

            user_name = ctx.user.nick if ctx.user.nick else ctx.user.global_name #use guild nickname if available, otherwise use global name

            logging.error(f'User {user_name} tried to view the mentor leaderboard, but an unexpected error occured: {e}')

            await ctx.send('An unknown error has occured. Please contact a HackKU organizer.', ephemeral=True)
#1}}}
print(f"DEBUG: API_TOKEN={config['API_TOKEN']}")
bot.run(config['API_TOKEN'])
