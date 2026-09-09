# Recreating the Masters of Interactive Light

_This project is to be done in teams of 2._

**COLLABORATORS:** Jaclyn Pham (add teammate name)

**THE MASTERWORK YOU DREW FROM THE HAT:** Rain Room (Random International, 2012)

---

One way to understand greatness is to look to the greats. Just as painters learn
the technique and artistry of the old masters by recreating their paintings, so
too shall we come to understand computer-mediated interaction by recreating the
interactive masterworks of our time.

This week, every team will draw a different masterwork from a hat. Some are
conceptual pieces, some are historical works, some are modern-day products —
but they all share one thing: **their central mode of interaction is carried by
light.** Think of Tinker Bell in the original stage production of *Peter Pan*,
represented by nothing more than a darting circle of light from an off-stage
mirror. There was no actor playing Tinker Bell; she existed entirely through the
way the other characters interacted with that light.

Your job is to recreate the *interaction* of the piece you drew — not to build a
museum-grade replica, but to stage the moment that makes it what it is. Someone
who knows your piece should watch your recreation and recognize it instantly.
Someone who has never heard of it should walk away understanding what it is
famous for.

You will do this using the interaction staging techniques we will use all semester: a
storyboard, some acting, a phone standing in as a controllable light (the
*Tinkerbelle* tool), a hidden human "wizard" driving it, a costume, and a
recorded video.

*Make sure you read all the instructions and understand the whole activity
before starting!*

## Prep

To start, you will need:

1. Read about Git [here](https://git-scm.com/book/en/v2/Getting-Started-What-is-Git%3F).
2. Set up your own Github "Lab Hub" by forking the [Interactive-Lab-Hub repository](https://github.com/IRL-CT/Interactive-Lab-Hub). To get lab updates, simply use [GitHub's "Sync fork" button](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/syncing-a-fork) when new content is available.

3. Set up your `README.md` so it has your name and links to this lab. Learn to
   format a README [here](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax).
4. **Draw your masterwork from the hat and write it at the top of this file.**
   Whatever you drew is yours — lean into it.

## Materials

For this lab you will need:

1. Paper, markers/pens, scissors
2. A smartphone with a browser that can display a webpage (your stand-in "light")
3. A computer to host the control webpage
4. Found objects and materials to **costume your phone so it looks like the
   device in your masterwork** — doll clothes, a paper lantern, a bottle, foil,
   a cardboard shell, whatever it takes. Be resourceful.

## Deliverables

Submit all of the following in this lab folder of your Lab Hub, as links or
uploaded files. **Each group member posts their own copy to their own Github repo**, even if the work is
shared.

1. A short **research write-up** of your masterwork (what it is, when, who made
   it, and — most importantly — what the interaction is)
2. **3 iterated storyboards** of the interaction in the masterwork
5. A **video sketch** of your prototyped interaction
6. Any **reflections** on the process

Labs are due on Mondays. Make sure this page is linked from your main class hub
page.

---

# The Report

## Part 0. Know Your Master

Before you prototype anything, get intimately acquainted with the piece you
drew. Do real research. You are looking less for trivia than for the *shape of
the interaction*:

- What inputs are available to the user? What responses does the work give?
- Who is present, and how does the piece color the relationships between them?
- What is the piece famous for? What are its strengths and its weaknesses?

  Sometimes the details of how the interaction worked are lost in history. Try filling it in with your imagination!

**Describe your masterwork here, in your own words. What is the core interaction
someone would recognize it by?**
Rain Room is a piece from 2012, created by Random International founded in 2005 by Hannes Kock and Florian Ortkrass. Random International is a postdigital art group exploring the human condition expressing the impact of technological development. They fabricate large-scale interactive pieces, and have a global team that operates through their headquarters in London. Random International prides themselves on experimenting interactions through natural and intuitive behaviour which instigates subjective experiences of consciousness. 

The room uses 3D tracking cameras and sensors to detect where people are place in the 3D space, and shuts off the water directly above them. So one can walk straight through a downpour and stay completely dry.
The core interaction is simple: the user moves, and the rain does not downpour on the user . Cameras read the user’s body as they navigate the space, and the ceiling turns off the valves above you, opening up a dry pocket that follows you around. Everyone can hear and smell the rain, and see it pouring down all around them, but no one gets wet.


## Part A. Plan

For your masterwork, reconstruct the interaction as a scene:

- **Setting:** Where and when does this interaction happen? (a jungle, a kitchen,
  a spaceship corridor, a nightclub, a harbor at night)
  Your body and your movement, picked up by overhead 3D cameras and sensors. The rain stops around the moving subject, preventing the user from getting rained on.
- **Players:** Who is involved? Who else is present? Think through everyone in
  the setting, not just the primary user.
  The visitors sharing the space of the installation when walking under the rain piece. 
- **Activity:** What is happening between the players and the light?
The visitor walks through a field of rain-like light. They test what happens when they move fast or slow, hold still, or step closer. They are not trying to see their own face; they are trying to feel a dry pocket open around them. 
- **Goals:** What is each player trying to do?
The feeling of controlling the rain, of being dry in the middle of a storm. Its strength is how natural the motion detection is that reacts seamlessly with movement. 

**Describe your setting, players, activity, and goals here.**

Now **sketch a 3 storyboards** of the interaction you are recreating. (The number may depend on the thing you drew, but stretch your thinking!) They
don't need to be beautiful, but they must capture and communicate not only the behavior of the light, but how it affects
and the people around it. If you're new to storyboarding, read
[this explanation](https://www.nngroup.com/articles/storyboards-visualize-ideas/).

**Include pictures of your storyboards here.**

Storyboard 1 — body on screen, rain-like blobs pushed around the silhouette:

![Storyboard](/Lab%201/lab1a-storyboard.png)

Storyboard 2 — after acting it out: camera/projector setup, still vs. motion, elements smushed around the silhouette instead of a live self-view:

![Storyboard](/Lab%201/lab1b-storyboard.png)

Later storyboard iterations (Drive folder): [Lab1-Liquid Motion](https://drive.google.com/drive/folders/1PRcRjMav0NMrCGIRu2mQAiCHG1PCvWv7)

Use the storyboards to decide what interaction to prototype.

**Summarize the feedback you got here.**
“Motion Liquid”: We rebuilt the feel of that relationship using a webcam and motion detection instead of water. The camera watches a still scene; when a person moves, their motion becomes a rippling, water-like displacement on screen. The person is the positive space the effect responds to, and the liquid ripple stands in for Rain Room’s water, the visible trace of the boundary between the body and the element reacting to it.

Classmates watching the first iteration did not understand the cue of movement — it was not obvious that *moving* was what made the rain react. We added more reactive components so motion would read immediately. For the second iteration we removed the human body from the canvas entirely (only a trail / cursor remains). For the third iteration we staged the same idea with Tinkerbelle: walking closer to the light turns it from yellow to blue, so proximity reads as the dry pocket opening in the rain.

## Part B. Act out the Interaction

Physically act out the interaction you planned. For now, just pretend the light
is doing what you've scripted — a person can wave a flashlight, or you can narrate
it aloud.

**Are there things that seemed better on paper than when acted out?**
On paper, putting the person on screen felt like the obvious way to show the Rain Room relationship: you move, the “rain” reacts around you. Acting it out, that readout did not hold. Seeing your own face and body on the canvas read as a webcam mirror, not as weather making space for you. Classmates also pointed out that the sketch was missing the factors that actually make Rain Room recognizable — the dry pocket, the trail of absence in the downpour — so we updated the storyboard to mimic that rain interaction instead of a self-view.

**Did new ideas about the piece surface once you were on your feet?**
Yes. Once we were standing in front of the camera, it became clear that any live reflection of the body would be read as a mirror, which is the opposite of what we want. The new idea was to take the human physical appearance off the canvas entirely and leave only the trail of movement. Right now that trail is represented as a cursor: the person is gone from the image, but their path through the space is still visible, and that path is what the rain-like effect can follow.

**Are there key moments in the interaction where things could go in a different direction?**
A few. If someone holds still, the cursor/trail can freeze and the “rain” can close back in, which is closer to Rain Room — or it can linger, which would feel more like a drawing than weather. If the body ever reappears on screen, the piece snaps back into mirror mode. Speed also splits the interaction: slow movement reads as a dry pocket following you; fast movement turns into a streak that might look like a mouse rather than a person walking through rain. Those are the beats we are still choosing between as we iterate.

Iterate your storyboards to capture key non-sequential aspects of the interaction. We redrew for stillness vs. walking, then for “no body on the canvas,” then for proximity as a yellow-to-blue Tinkerbelle light. Those later boards and stills: [Lab1-Liquid Motion](https://drive.google.com/drive/folders/1PRcRjMav0NMrCGIRu2mQAiCHG1PCvWv7)

## Part C. Prototype the Light (light first!)

Use your smartphone as the light of your device. Open the browser on your phone
to act as the "light," and use the remote control interface on your computer to
change that light. Code and setup instructions for the *Tinkerbelle* tool are
[here](https://github.com/IRL-CT/tinkerbelle) (we invented this tool for
this lab). If you hit technical trouble, a manually or remotely controlled light
switch, dimmer, or lamp is a fine substitute.

**Get the light interaction working before anything else.** Your grade this week
rides on the *light* being recognizable — the color, the rhythm, the timing, the
way it answers a person. Only once your light interaction genuinely reads as your
masterwork should you consider layering in a second modality (sound, vibration,
motion). If in doubt, keep polishing the light. The other modalities are next
week's business.

**What we prototyped with Tinkerbelle.** The phone is the rain. Yellow is the downpour; blue is the dry pocket that opens when you enter the field. In the Tinkerbelle pass, a person walks toward the light: as the walking distance closes, the wizard (or the mapped control) turns the light from yellow to blue. That color change is the Rain Room beat — you are in the storm, then the rain yields around you.

Tinkerbelle video: https://drive.google.com/file/d/1qXx91BrkMB19Rr076hatK2aJi3MfC0Hk/view

## Part D. Wizard the Device

Set up a "wizard" arrangement so one person can secretly drive the light while
another acts with it — this is how you make the device feel alive without
building any real electronics. (Zoom works well for recording; you can pin the
video feed of whichever scene you want to capture.)

**Include your first attempts at recording the wizarded set-up here.**

**Iteration 1.** Webcam “Motion Liquid” with the person still visible. Classmates did not get that movement was the cue, so we pushed the reaction harder (more ripple / more of the field responding).  
https://drive.google.com/file/d/12va8TiJYj4_cx5fHg-4fBY5YO5Ymcz47/view?usp=drive_link

**Iteration 2.** Same wizarded camera setup, but the human body is gone from the canvas. Only the trail of movement remains, so it cannot be read as a mirror.  
https://drive.google.com/file/d/1QgDi0GIhTpSE0mc1MsXllnCILRW41ft-/view?usp=drive_link

**Iteration 3.** Tinkerbelle as the rain light: walk closer → yellow to blue.  
https://drive.google.com/file/d/1qXx91BrkMB19Rr076hatK2aJi3MfC0Hk/view

## Part E. (optional) Costume the Device

Only now should you worry about what the device looks like. Costume your phone so it reads
as the object from your masterwork — HAL's eye, a Simon shell, a paper-lantern
Tinker Bell, an Ambient Orb, a lighthouse, a jack-o'-lantern, whatever you drew.

Think about the world your device lives in: could that environment overheat it?
Is water a danger? Does it need to be loud and bright for an emergency, or quiet
and calm for a bedroom?

**Include sketches/photos of what your device might look like here.**

We did not wrap the phone in a miniature Rain Room. The “costume” is the light itself: a field that should read as weather, not as a gadget. In the storyboards that look is a projector screen of colored, water-like blobs; in the Tinkerbelle sketch it is a phone filling with yellow (rain) or blue (the dry pocket). Extra storyboard and stills live in the same Drive folder: [Lab1-Liquid Motion](https://drive.google.com/drive/folders/1PRcRjMav0NMrCGIRu2mQAiCHG1PCvWv7)

**What concerns or opportunities shaped the way you designed its look?**
Rain Room’s actual material is water, which is a bad partner for a phone. Using light as the rain lets us keep the famous relationship — the field yields around a body — without soaking hardware. The other design worry was looking like a mirror: any live video of the visitor’s face would steal the piece. So the look we committed to is *absence of the body* plus a color or ripple that follows the path. Yellow vs. blue on Tinkerbelle is a simple costume for that idea: storm, then shelter.

## Part F. Record

**Record your prototyped interaction as a video sketch.** Aim for the bar from
the top of this lab: a viewer who knows the piece should recognize it; a viewer
who doesn't should come away understanding what it's famous for. How might you illustrate the non-sequential aspects of the interaction in the sketch?

**Include your video here.**

The video sketch that is meant to carry the masterwork is the Tinkerbelle pass: someone walks toward the light, and it turns from yellow (rain) to blue (dry). That is the non-sequential beat — it is not a timeline of “then this happens,” it is a relationship you can enter from any distance.

- Tinkerbelle (video sketch): https://drive.google.com/file/d/1qXx91BrkMB19Rr076hatK2aJi3MfC0Hk/view
- First iteration (body on screen, movement cue too weak): https://drive.google.com/file/d/12va8TiJYj4_cx5fHg-4fBY5YO5Ymcz47/view?usp=drive_link
- Second iteration (body removed, trail only): https://drive.google.com/file/d/1QgDi0GIhTpSE0mc1MsXllnCILRW41ft-/view?usp=drive_link

**Please indicate who you collaborated with on this lab.** Be generous in
acknowledging their contributions, and credit any other influences (YouTube,
Github, Twitter, a friend who lent you a lamp) that informed your recreation.

Worked as a pair on this lab (Jaclyn Pham — add teammate). Classmates after the first iteration told us the movement cue was not readable, which is why we added stronger reactive components, then stripped the body off the canvas, then mapped proximity onto Tinkerbelle’s yellow-to-blue light. The [Tinkerbelle](https://github.com/IRL-CT/tinkerbelle) tool is the FAR Lab / IRL-CT remote light we used for the third pass. The masterwork is [Rain Room](https://www.random-international.com/rain-room-2012) by Random International. Webcam motion detection stood in for their 3D tracking cameras.

---

# Part 2 — ReMastering the light

*This describes the second week's work for this lab activity.*

## Prep (before the next lab)

Find three other groups. (How? Maybe Slack?) Visit their Lab Hub pages, watch their
videos, and give them reactions and feedback: tell them what you saw happening,
guess the masterwork and the goals of the characters, and ask about anything that
wasn't clear.

**Who were the other groups you kibitzed with? Add links to their project pages here.**

- [The Traffic Light](https://github.com/MortalJin/Interactive-Lab-Hub/tree/Fall2026/Lab%201) — Yangchen Jin and Omar Shair
- The pixel art neon light project (add Hub link)

**Summarize the feedback you got from your partners here.**

**What we saw on their pages.** Both pieces are super cool. The Traffic Light group staged a very readable street scene: red / yellow / green as stop, ready, go, with pedestrians and drivers as the players. Their first pass used a traffic-light app rather than Tinkerbelle, and the interaction was still instantly recognizable as a crossing. The pixel art neon light project was visually strong in a different way — the glow and the “screen as sign” feeling came through even without a Tinkerbelle phone in the frame.

**What wasn’t clear — for them, and for us.** Watching those Hubs, and talking in studio, it felt like the whole class was still confused about what this lab is *for*. The write-up asks for a wizarded Tinkerbelle light, but none of us (Traffic Light, pixel-art neon, or our Rain Room pass) showed a prototype that was obviously driven with Tinkerbelle in the first round. We all reached for whatever made the masterwork legible: an app, a webcam field, a neon graphic. The gap is not that the pieces are weak; it is that the assignment’s tool (a remotely controlled phone-light) and the thing we actually needed to prove (the interaction someone would recognize) did not line up in anyone’s first video.

**Feedback on our Rain Room piece.** Classmates still said the first Motion Liquid pass did not make movement the obvious cue. That is why we added more reactive components, then took the body off the canvas, and only later mapped walking-closer onto a Tinkerbelle yellow-to-blue light — after seeing that nobody else had used Tinkerbelle either.

## Remix, Update, or Critique the Master

Now that you understand your masterwork from the inside, respond to it. Do the
recreation again, but this time make it your own — pick one of these moves (or
combine them):

1. **Remix the modality.** Your recreation no longer has to (just) use light. Use
   vibration, sound, motion, heat — whatever best carries the interaction. Feel
   free to fork and modify the Tinkerbelle code. (Add your updates to this lab's folder!)
2. **Update it.** Redesign the piece for today's context, or for a setting its
   creators never imagined (the piece with roommates in the room, with children
   present, on a phone, in a car).
3. **Fix its weaknesses.** You identified this master's strengths and weaknesses
   in Part 0 — now address a weakness, or push a strength further.

We will grade this second pass with an emphasis on **creativity** and on how well
your response engages with what your master was really doing.

**Document everything here — especially the storyboard and video. Photos of the
prototype are great too.**

---



*Assignment lineage: this lab merges "Staging Interaction" (Interactive Lab Hub)
with "Recreating the Masters" (Interaction Design Studio, Profs. Scott Minneman &
Wendy Ju). Massive list of interactive light masterworks generated by Claude.ai.*
